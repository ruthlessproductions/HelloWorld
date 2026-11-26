#!/usr/bin/env python3
"""Generate video on fal.ai from a text prompt or a Blender shot's control passes, with a cost check first.

Usage:
  python3 scripts/fal_video.py MODEL --prompt "..." [--passes scenes/shot/passes] [--out DIR] \
      [--resolution 480p] [--duration 4] [--aspect 2.39] [--seed 1] [--ref-image style.png] \
      [--max-cost 2.0] [--yes]

Models:
  wan-depth     fal-ai/wan-vace-14b/depth: follows the depth pass frame by frame, so it keeps the
                Blender camera, layout and timing (the pass is used as-is, no depth estimation)
  seedance-ref  bytedance/seedance-2.5/reference-to-video: uses the beauty pass as a reference video
                for composition and motion; looser, but free to invent more
  kling-t2v     fal-ai/kling-video/v3/standard/text-to-video: prompt only, 16:9, no audio
  seedance-t2v  bytedance/seedance-2.5/text-to-video: prompt only, 21:9, no audio
  seedance-img  bytedance/seedance-2.5/reference-to-video with --ref-image stills only (look,
                composition), 21:9, no audio
  seedance-i2v  bytedance/seedance-2.5/image-to-video: animates --start-image (and optionally ends
                on --end-image); the frame's aspect sets the video's, no audio

The first two need --passes; the text-to-video models need --out and take --duration (seconds).
--aspect crops the result to that width/height (e.g. 2.39) for comparing with a reference.

--ref-image (wan-depth; repeatable) adds an image of the intended look. Depth alone can't tell
sea from fields or glass from terraces; a reference image settles what the surfaces are.

The passes folder comes from the Blender skill's render_passes.py (it reads passes.json there).
Without --yes it only prints what it would send and the estimated cost; with --yes it submits,
waits, downloads the result, and (for wan-depth) crops and trims it back to the shot's frame.
Refuses to submit when the estimate is over --max-cost. Needs FAL_KEY in the environment.
Each submitted request is recorded in <out>/pending_<id>.json until its result is downloaded; if
the wait is interrupted, collect it with --resume <id> (same model and --out) instead of resubmitting.
Standard library only.
"""

import argparse
import base64
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

MODELS = {
    "wan-depth": {
        "endpoint": "fal-ai/wan-vace-14b/depth",
        "pass": "depth",
        # fal lists $0.08/s at 720p, $0.06/s at 580p and $0.04/s at 480p; the pricing API
        # returns the 720p rate, so scale by resolution.
        "res_scale": {"480p": 0.5, "580p": 0.75, "720p": 1.0},
        "sizes": {"480p": (848, 480), "580p": (1024, 576), "720p": (1280, 720)},   # 16:9, even sizes
        "min_frames": 81,
    },
    "seedance-ref": {
        "endpoint": "bytedance/seedance-2.5/reference-to-video",
        "pass": "beauty",
        # tokens = height * width * (reference seconds + output seconds) * 24 / 1024,
        # priced per 1000 tokens, times 0.6 when a video reference is included
        "sizes": {"480p": (992, 432), "720p": (1488, 648)},                        # 21:9 as delivered
        "min_seconds": 4,
    },
    "kling-t2v": {
        "endpoint": "fal-ai/kling-video/v3/standard/text-to-video",
        "pass": None,
        "sizes": {"standard": None},
        "params": {"aspect_ratio": "16:9", "generate_audio": False},
    },
    "seedance-img": {
        "endpoint": "bytedance/seedance-2.5/reference-to-video",
        "pass": None,
        "sizes": {"480p": (992, 432), "720p": (1488, 648)},                        # 21:9 as delivered
        "params": {"aspect_ratio": "21:9", "generate_audio": False},
    },
    "seedance-i2v": {
        "endpoint": "bytedance/seedance-2.5/image-to-video",
        "pass": None,
        "sizes": {"480p": (992, 432), "720p": (1470, 630)},                        # for 21:9 frames
        "params": {"generate_audio": False},
    },
    "seedance-t2v": {
        "endpoint": "bytedance/seedance-2.5/text-to-video",
        "pass": None,
        "sizes": {"480p": (992, 432), "720p": (1488, 648)},                        # 21:9 as delivered
        "params": {"aspect_ratio": "21:9", "generate_audio": False},
    },
}


def http(method, url, key, body=None, timeout=120, retries=None):
    """JSON request to fal. GETs retry on dropped connections; POSTs never retry (a repeated submit
    would be a second paid job)."""
    retries = (6 if method == "GET" else 0) if retries is None else retries
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Key {key}", "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as err:
            if err.code >= 500 and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            sys.exit(f"fal returned HTTP {err.code} for {url}:\n{err.read().decode(errors='replace')[:2000]}")
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as err:
            if attempt < retries:
                print(f"  connection problem ({err}); retrying")
                time.sleep(2 ** attempt)
                continue
            raise


def unit_price(endpoint, key):
    prices = http("GET", f"https://api.fal.ai/v1/models/pricing?endpoint_id={endpoint}", key).get("prices", [])
    if not prices:
        sys.exit(f"no price listed for {endpoint}")
    return prices[0]["unit_price"], prices[0]["unit"]


def ffmpeg(*args):
    exe = shutil.which("ffmpeg")
    if not exe:
        sys.exit("ffmpeg is needed on PATH")
    subprocess.run([exe, "-v", "error", "-y", *args], check=True)


def data_uri(path, mime="video/mp4"):
    with open(path, "rb") as fh:
        return f"data:{mime};base64," + base64.b64encode(fh.read()).decode()


def prepare(model, cfg, meta, passes_dir, work, resolution):
    """Make the upload video and the request input; return (input, estimate info)."""
    fps = meta["fps"]
    n_frames = meta["frames"][1] - meta["frames"][0] + 1
    src = os.path.join(passes_dir, f"{cfg['pass']}.mp4")
    if not os.path.exists(src):
        sys.exit(f"missing {src}: run render_passes.py with the {cfg['pass']} pass")
    os.makedirs(work, exist_ok=True)
    if model == "wan-depth":
        w, h = cfg["sizes"][resolution]
        frames = max(n_frames, cfg["min_frames"])
        clip = os.path.join(work, f"{os.path.basename(passes_dir)}_depth_{resolution}.mp4")
        pw, ph = meta["resolution"]
        if abs(pw / ph - w / h) > 0.02:
            print(f"note: passes are {pw}x{ph}, not 16:9; padding with black bars, which the model reads as far "
                  f"away. Render the passes with --overscan 16:9 instead.")
        # Fit to 16:9 and hold the last frame to reach the minimum length
        ffmpeg("-i", src, "-vf", f"scale={w}:-2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
               f"tpad=stop_mode=clone:stop={frames - n_frames},fps={fps}", "-frames:v", str(frames),
               "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", clip)
        return clip, {"num_frames": frames, "frames_per_second": int(round(fps)), "resolution": resolution,
                      "aspect_ratio": "16:9", "preprocess": False}, frames / fps
    seconds = max(cfg["min_seconds"], int(round(n_frames / fps + 0.49)))
    return src, {"duration": str(seconds), "resolution": resolution, "aspect_ratio": "21:9",
                 "generate_audio": False}, seconds


def estimate(model, cfg, resolution, out_seconds, ref_seconds, key):
    price, unit = unit_price(cfg["endpoint"], key)
    if model == "kling-t2v":
        return price * out_seconds, f"${price}/{unit} x {out_seconds} s"
    if model in ("seedance-t2v", "seedance-img", "seedance-i2v"):   # no video reference: no 0.6 multiplier
        w, h = cfg["sizes"][resolution]
        tokens = h * w * out_seconds * 24 / 1024
        return price * tokens / 1000, f"${price}/{unit} x {tokens:,.0f} tokens ({w}x{h}, {out_seconds} s)"
    if model == "wan-depth":
        cost = price * out_seconds * cfg["res_scale"][resolution]
        note = f"${price}/{unit} (720p) x {cfg['res_scale'][resolution]} for {resolution} x {out_seconds:.2f} s"
        return cost, note
    w, h = cfg["sizes"][resolution]
    with_ref = h * w * (ref_seconds + out_seconds) * 24 / 1024
    without_ref = h * w * out_seconds * 24 / 1024
    high = price * with_ref / 1000 * 0.6
    low = price * without_ref / 1000 * 0.6
    note = (f"${price}/{unit}; {without_ref:,.0f}-{with_ref:,.0f} tokens x 0.6 (video reference) "
            f"= ${low:.2f}-${high:.2f}; using the higher figure")
    return high, note


def queue_urls(endpoint, request_id):
    """Status and result URLs for a request (fal's queue addresses requests by owner/app)."""
    app = "/".join(endpoint.split("/")[:2])
    base = f"https://queue.fal.run/{app}/requests/{request_id}"
    return base + "/status", base


def submit_and_wait(endpoint, payload, key, pending_dir):
    queued = http("POST", f"https://queue.fal.run/{endpoint}", key, payload, timeout=300)
    request_id = queued.get("request_id")
    print(f"submitted: request {request_id}")
    # Record it before waiting, so a dropped connection can be resumed instead of resubmitted
    os.makedirs(pending_dir, exist_ok=True)
    with open(os.path.join(pending_dir, f"pending_{request_id}.json"), "w") as fh:
        json.dump({"endpoint": endpoint, "request_id": request_id, "status_url": queued["status_url"],
                   "response_url": queued["response_url"]}, fh, indent=2)
    return wait(queued["status_url"], queued["response_url"], request_id, key)


def wait(status_url, response_url, request_id, key):
    last = None
    while True:
        status = http("GET", status_url + "?logs=1", key)
        state = status.get("status")
        if state != last:
            extra = f" (queue position {status['queue_position']})" if status.get("queue_position") is not None else ""
            print(f"  {state}{extra}")
            last = state
        if state == "COMPLETED":
            return request_id, http("GET", response_url, key)
        if state not in ("IN_QUEUE", "IN_PROGRESS"):
            sys.exit(f"request ended with status {state}: {json.dumps(status)[:1000]}")
        time.sleep(5)


def main():
    sys.stdout.reconfigure(line_buffering=True)      # progress shows up in logs as it happens
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=sorted(MODELS))
    parser.add_argument("--passes", help="render_passes.py output (needed for wan-depth and seedance-ref)")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--resolution", default="480p")
    parser.add_argument("--out", help="where results go (default: <passes>/../fal)")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--duration", type=int, default=4, help="seconds, for text-to-video models")
    parser.add_argument("--aspect", type=float, help="crop the result to this width/height, e.g. 2.39")
    parser.add_argument("--ref-image", action="append", default=[], help="image of the intended look (wan-depth)")
    parser.add_argument("--start-image", help="first frame (seedance-i2v)")
    parser.add_argument("--end-image", help="last frame (seedance-i2v, optional)")
    parser.add_argument("--name", help="prefix for the output files (default: the model name)")
    parser.add_argument("--max-cost", type=float, default=2.0, help="refuse to submit above this (USD)")
    parser.add_argument("--yes", action="store_true", help="actually submit (otherwise estimate only)")
    parser.add_argument("--resume", metavar="REQUEST_ID", help="collect an already-submitted request (no new job)")
    args = parser.parse_args()

    key = os.environ.get("FAL_KEY")
    if not key:
        sys.exit("FAL_KEY is not set")
    cfg = MODELS[args.model]
    if args.resolution not in cfg["sizes"]:
        sys.exit(f"{args.model} supports {', '.join(cfg['sizes'])}")
    text_only = cfg["pass"] is None
    if text_only:
        if not args.out:
            sys.exit("text-to-video models need --out")
        passes_dir, meta, clip = None, None, None
        out_dir = os.path.abspath(args.out)
        shot_frames, shot_seconds = None, None
        params = dict(cfg["params"], duration=str(args.duration))
        if args.resolution in (cfg["sizes"] or {}) and cfg["sizes"][args.resolution]:
            params["resolution"] = args.resolution
        out_seconds = args.duration
    else:
        if not args.passes:
            sys.exit(f"{args.model} needs --passes")
        passes_dir = os.path.abspath(args.passes)
        with open(os.path.join(passes_dir, "passes.json")) as fh:
            meta = json.load(fh)
        out_dir = os.path.abspath(args.out or os.path.join(passes_dir, "..", "fal"))
        shot_frames = meta["frames"][1] - meta["frames"][0] + 1
        shot_seconds = shot_frames / meta["fps"]
        clip, params, out_seconds = prepare(args.model, cfg, meta, passes_dir, os.path.join(out_dir, "_inputs"),
                                            args.resolution)
    os.makedirs(out_dir, exist_ok=True)
    cost, note = estimate(args.model, cfg, args.resolution, out_seconds, shot_seconds, key)
    print(f"model:    {cfg['endpoint']}")
    if clip:
        print(f"sends:    {os.path.relpath(clip)} ({os.path.getsize(clip) / 1024:.0f} KB) + prompt")
    else:
        print("sends:    prompt only")
    for ref in args.ref_image:
        if not os.path.exists(ref):
            sys.exit(f"missing reference image {ref}")
        print(f"          reference image {ref} ({os.path.getsize(ref) / 1024:.0f} KB)")
    if args.ref_image and args.model not in ("wan-depth", "seedance-img"):
        sys.exit("--ref-image is only wired up for wan-depth and seedance-img")
    if args.model == "seedance-img" and not args.ref_image:
        sys.exit("seedance-img needs at least one --ref-image")
    if args.model == "seedance-i2v":
        if not args.start_image:
            sys.exit("seedance-i2v needs --start-image")
        for frame in filter(None, (args.start_image, args.end_image)):
            if not os.path.exists(frame):
                sys.exit(f"missing frame {frame}")
            print(f"          frame {frame} ({os.path.getsize(frame) / 1024:.0f} KB)")
    print(f"params:   {json.dumps(params)}")
    print(f"estimate: ${cost:.2f}  ({note})")
    payload = dict(params, prompt=args.prompt)
    if args.resume:
        pending = os.path.join(out_dir, f"pending_{args.resume}.json")
        if os.path.exists(pending):
            with open(pending) as fh:
                rec = json.load(fh)
            status_url, response_url = rec["status_url"], rec["response_url"]
        else:
            status_url, response_url = queue_urls(cfg["endpoint"], args.resume)
        print(f"resuming request {args.resume} (no new job is submitted)")
        request_id, result = wait(status_url, response_url, args.resume, key)
        return finish(args, cfg, params, payload, result, request_id, out_dir, meta, passes_dir, shot_frames, cost)
    if not args.yes:
        print("dry run: nothing sent. Add --yes to submit.")
        return
    if cost > args.max_cost:
        sys.exit(f"estimate ${cost:.2f} is over --max-cost ${args.max_cost:.2f}; not submitting")

    if args.seed is not None:
        payload["seed"] = args.seed
    if args.model == "wan-depth":
        payload["video_url"] = data_uri(clip)
        if args.ref_image:
            payload["ref_image_urls"] = [data_uri(r, "image/png" if r.lower().endswith(".png") else "image/jpeg")
                                         for r in args.ref_image]
    elif args.model == "seedance-i2v":
        payload["image_url"] = data_uri(args.start_image, "image/png" if args.start_image.lower().endswith(".png")
                                        else "image/jpeg")
        if args.end_image:
            payload["end_image_url"] = data_uri(args.end_image, "image/png" if args.end_image.lower().endswith(".png")
                                                else "image/jpeg")
    elif args.model == "seedance-img":
        payload["image_urls"] = [data_uri(r, "image/png" if r.lower().endswith(".png") else "image/jpeg")
                                 for r in args.ref_image]
    elif args.model == "seedance-ref":
        payload["video_urls"] = [data_uri(clip)]
        payload["prompt"] = args.prompt + " Follow the composition, camera move and timing of [Video1]."
    request_id, result = submit_and_wait(cfg["endpoint"], payload, key, out_dir)
    finish(args, cfg, params, payload, result, request_id, out_dir, meta, passes_dir, shot_frames, cost)


def finish(args, cfg, params, payload, result, request_id, out_dir, meta, passes_dir, shot_frames, cost):
    """Download the result, crop it for comparison, and log the request."""
    video_url = (result.get("video") or {}).get("url")
    if not video_url:
        sys.exit(f"no video in the result: {json.dumps(result)[:1000]}")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(out_dir, f"{args.name or args.model}_{args.resolution}_{stamp}.mp4")
    urllib.request.urlretrieve(video_url, raw_path)
    print(f"downloaded {os.path.relpath(raw_path)}")
    final = raw_path
    if args.model == "wan-depth":
        # Back to the shot's aspect (the overscan crop, or undo the letterbox) and frame count
        w, h = meta.get("crop", {}).get("shot_resolution") or meta["resolution"]
        final = raw_path.replace(".mp4", "_shot.mp4")
        ffmpeg("-i", raw_path, "-vf", f"crop=iw:iw*{h}/{w}:0:(ih-iw*{h}/{w})/2", "-frames:v", str(shot_frames),
               "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", final)
        print(f"cropped to the shot: {os.path.relpath(final)}")
    elif args.aspect:
        final = raw_path.replace(".mp4", f"_{args.aspect:g}.mp4")
        ffmpeg("-i", raw_path, "-vf", f"crop='min(iw,ih*{args.aspect})':'min(ih,iw/{args.aspect})',"
               "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", final)
        print(f"cropped to {args.aspect:g}:1: {os.path.relpath(final)}")
    log = {"model": cfg["endpoint"], "request_id": request_id, "params": params, "prompt": payload["prompt"],
           "passes": os.path.relpath(passes_dir) if passes_dir else None, "ref_images": args.ref_image,
           "start_image": args.start_image, "end_image": args.end_image,
           "seed": result.get("seed"), "estimate_usd": round(cost, 3), "video_url": video_url,
           "files": [os.path.relpath(raw_path), os.path.relpath(final)]}
    with open(raw_path.replace(".mp4", ".json"), "w") as fh:
        json.dump(log, fh, indent=2)
    pending = os.path.join(out_dir, f"pending_{request_id}.json")
    if os.path.exists(pending):
        os.remove(pending)


if __name__ == "__main__":
    main()
