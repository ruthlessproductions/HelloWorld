#!/usr/bin/env python3
"""Generate Seedream stills and Seedance video through Oxen.ai's inference API, with a cost check first.

Usage:
  python3 scripts/oxen.py image --prompt "..." --out DIR [--name frame] [--count 2]
      [--size 2240x960] [--ref-image ref.png ...] [--max-cost 0.5] [--yes]
  python3 scripts/oxen.py video --prompt "..." --out DIR [--name shot1]
      [--start-image first.png [--end-image last.png] | --ref-image look.png ...]
      [--resolution 480p] [--duration 4] [--aspect-ratio 21:9] [--count 1] [--aspect 2.39]
      [--max-cost 2.0] [--yes]
  python3 scripts/oxen.py {image|video} --out DIR --resume GENERATION_ID [...]

image  Seedream 4 (bytedance-seedream-4). --ref-image files (up to 14; refer to them in the prompt as
       @Image1, @Image2 ...) make it an edit/compose of those images. --size is 1K, 2K, 4K or WxH.
video  Seedance 2.5. --start-image (and optional --end-image) picks image-to-video, animating
       between keyframes with the frame's own aspect; --ref-image stills pick reference-to-video (the
       look, refer to them as @Image1 ...); neither picks text-to-video. No audio, no watermark.

The price and the accepted parameters come from Oxen's public model catalog, so the estimate is
exact and a request the model wouldn't accept is refused here rather than failing after queueing.
Without --yes it only prints what it would send and the estimate; nothing is sent. Refuses to
submit over --max-cost. Jobs go through Oxen's async queue and are recorded in
<out>/pending_<name>.json until downloaded; if the wait is interrupted, collect them with --resume
<generation id ...> instead of resubmitting. Needs OXEN_API_KEY in the environment for submitting.
Standard library only.
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fal_video import data_uri, ffmpeg  # noqa: E402

BASE = "https://hub.oxen.ai/api/ai"
IMAGE_MODEL = "bytedance-seedream-4"
VIDEO_MODELS = {"i2v": "bytedance-seedance-2-5-image-to-video",
                "ref": "bytedance-seedance-2-5-reference-to-video",
                "t2v": "bytedance-seedance-2-5-text-to-video"}
DONE = ("succeeded", "failed", "cancelled")


def http(method, url, key=None, body=None, timeout=120, retries=None):
    """JSON request to Oxen. GETs retry on dropped connections; POSTs never retry (a repeated submit
    would be a second paid job)."""
    retries = (6 if method == "GET" else 0) if retries is None else retries
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as err:
            if err.code >= 500 and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            sys.exit(f"Oxen returned HTTP {err.code} for {url}:\n{err.read().decode(errors='replace')[:2000]}")
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as err:
            if attempt < retries:
                print(f"  connection problem ({err}); retrying")
                time.sleep(2 ** attempt)
                continue
            raise


def model_info(model_id):
    info = http("GET", f"{BASE}/models/{model_id}")
    return info.get("data", info)


def check_params(model_id, info, params):
    """Refuse parameters the model's request_schema doesn't list, or enum values it doesn't allow."""
    props = (info.get("request_schema") or {}).get("properties", {})
    for name, value in params.items():
        if name not in props:
            sys.exit(f"{model_id} doesn't take '{name}' (it takes: {', '.join(sorted(props))})")
        allowed = props[name].get("enum")
        if allowed and value not in allowed and not (name == "size" and "x" in str(value)):
            sys.exit(f"{model_id}: {name} must be one of {allowed}, not {value!r}")


def image_uri(path):
    if not os.path.exists(path):
        sys.exit(f"missing image {path}")
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return data_uri(path, "image/" + {"jpg": "jpeg"}.get(ext, ext))


def image_size(path):
    """Width and height of a PNG or JPEG, without extra libraries."""
    with open(path, "rb") as fh:
        head = fh.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
        fh.seek(2)
        while True:
            marker, size = fh.read(2), int.from_bytes(fh.read(2), "big")
            if marker[1] in (0xC0, 0xC1, 0xC2):
                fh.read(1)
                h, w = int.from_bytes(fh.read(2), "big"), int.from_bytes(fh.read(2), "big")
                return w, h
            fh.seek(size - 2, 1)


def describe(label, path):
    w, h = image_size(path)
    print(f"sends:    {label} {path} ({w}x{h}, {w / h:.2f}:1, {os.path.getsize(path) / 1024:.0f} KB)")


def build(args):
    """Model, request parameters (without the images), per-job cost and a note on the price."""
    if args.kind == "image":
        model = args.model or IMAGE_MODEL
        info = model_info(model)
        params = {"prompt": args.prompt, "size": args.size, "watermark": False}
        if args.ref_image:
            params["input_image"] = args.ref_image
        price = info["pricing"]["cost_per_image"]
        return model, info, params, price, f"${price}/image"
    if args.ref_image and args.start_image:
        sys.exit("use either --start-image/--end-image (keyframes) or --ref-image (look), not both")
    if args.end_image and not args.start_image:
        sys.exit("--end-image needs --start-image")
    mode = "i2v" if args.start_image else "ref" if args.ref_image else "t2v"
    model = args.model or VIDEO_MODELS[mode]
    info = model_info(model)
    params = {"prompt": args.prompt, "duration": args.duration, "resolution": args.resolution,
              "generate_audio": False, "watermark": False}
    if mode == "i2v":
        params["input_image"] = args.start_image
        if args.end_image:
            params["tail_image_url"] = args.end_image
    else:
        params["aspect_ratio"] = args.aspect_ratio
        if mode == "ref":
            params["input_images"] = args.ref_image
    pricing = info["pricing"]
    per_second = (pricing.get("cost_per_second_by_resolution") or {}).get(args.resolution, pricing.get("cost_per_second"))
    return model, info, params, per_second * args.duration, f"${per_second}/s at {args.resolution} x {args.duration} s"


def with_images(params):
    """The request with local image paths swapped for data URIs."""
    out = dict(params)
    for name in ("input_image", "tail_image_url", "input_images"):
        if name in out:
            value = out[name]
            out[name] = [image_uri(p) for p in value] if isinstance(value, list) else image_uri(value)
    return out


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def main():
    sys.stdout.reconfigure(line_buffering=True)      # progress shows up in logs as it happens
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="kind", required=True)
    for kind in ("image", "video"):
        p = sub.add_parser(kind)
        p.add_argument("--prompt", default="")
        p.add_argument("--out", required=True)
        p.add_argument("--name", default=kind)
        p.add_argument("--model", help="Oxen model ID (default: Seedream 4 / Seedance 2.5 for the mode)")
        p.add_argument("--ref-image", action="append", default=[], help="reference image (repeatable)")
        p.add_argument("--count", type=int, default=1, help="variations to generate (1-4)")
        p.add_argument("--yes", action="store_true", help="actually submit (otherwise estimate only)")
        p.add_argument("--resume", nargs="+", metavar="GENERATION_ID", help="collect queued jobs (no new job)")
    img = sub.choices["image"]
    img.add_argument("--size", default="2K", help="1K, 2K, 4K or WxH (at least 921,600 pixels)")
    img.add_argument("--max-cost", type=float, default=0.5)
    vid = sub.choices["video"]
    vid.add_argument("--start-image", help="first frame (image-to-video)")
    vid.add_argument("--end-image", help="last frame (needs --start-image)")
    vid.add_argument("--resolution", default="480p")
    vid.add_argument("--duration", type=int, default=4, help="seconds (4-30 for Seedance 2.5)")
    vid.add_argument("--aspect-ratio", default="21:9", help="for text/reference-to-video; keyframes set their own")
    vid.add_argument("--aspect", type=float, help="crop the result to this width/height, e.g. 2.39")
    vid.add_argument("--max-cost", type=float, default=2.0)
    args = parser.parse_args()

    key = os.environ.get("OXEN_API_KEY")
    if not key and (args.yes or args.resume):      # dry runs don't need it
        sys.exit("OXEN_API_KEY is not set (create an API key in your Oxen.ai account settings and export it)")
    out = os.path.abspath(args.out)
    if args.resume:
        print(f"resuming {len(args.resume)} generation(s) (no new job is submitted)")
        return collect(args, key, out, args.resume, None, None)
    if not args.prompt:
        sys.exit("--prompt is required")
    if not 1 <= args.count <= 4:
        sys.exit("--count must be 1-4")
    model, info, params, unit_cost, note = build(args)
    check_params(model, info, params)
    cost = unit_cost * args.count
    print(f"model:    {model}")
    for label, name in (("start frame", "input_image"), ("end frame", "tail_image_url")):
        if args.kind == "video" and name in params:
            describe(label, params[name])
    for ref in args.ref_image:
        describe("reference image", ref)
    shown = {k: v for k, v in params.items() if k not in ("prompt", "input_image", "tail_image_url", "input_images")}
    print(f"params:   {json.dumps(shown)}")
    print(f"estimate: ${cost:.2f}  ({args.count} x {note})")
    if not args.yes:
        print("dry run: nothing sent. Add --yes to submit.")
        return
    if cost > args.max_cost:
        sys.exit(f"estimate ${cost:.2f} is over --max-cost ${args.max_cost:.2f}; not submitting")

    queued = http("POST", f"{BASE}/queue", key, dict(with_images(params), model=model, num_generations=args.count),
                  timeout=300)
    ids = [g["generation_id"] for g in queued.get("generations", [])]
    if not ids:
        sys.exit(f"nothing was queued: {json.dumps(queued)[:1000]}")
    print(f"queued:   {', '.join(ids)}")
    # Record them before waiting, so a dropped connection can be resumed instead of resubmitted
    os.makedirs(out, exist_ok=True)
    request = dict(params, model=model, count=args.count, estimate_usd=round(cost, 3))
    with open(os.path.join(out, f"pending_{args.name}.json"), "w") as fh:
        json.dump(dict(request, generation_ids=ids), fh, indent=2)
    collect(args, key, out, ids, request, cost)


def collect(args, key, out, ids, request, cost):
    """Wait for each generation, download it, crop if asked, and log the run."""
    pending = os.path.join(out, f"pending_{args.name}.json")
    if request is None and os.path.exists(pending):
        with open(pending) as fh:
            request = json.load(fh)
    os.makedirs(out, exist_ok=True)
    when, files, records = stamp(), [], []
    for i, gen_id in enumerate(ids, start=1):
        last = None
        while True:
            gen = http("GET", f"{BASE}/queue/{gen_id}", key)
            if gen.get("status") != last:
                last = gen.get("status")
                print(f"  {gen_id}: {last}")
            if last in DONE:
                break
            time.sleep(4 if args.kind == "image" else 10)
        records.append({k: v for k, v in gen.items() if not (isinstance(v, str) and len(v) > 500)
                        and k not in ("input_image", "input_images", "tail_image_url")})
        if last != "succeeded":
            print(f"  {gen_id} {last}: {gen.get('error_message')}")
            continue
        url = gen["result_url"]
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or (".png" if args.kind == "image" else ".mp4")
        suffix = f"_{i}" if len(ids) > 1 or args.kind == "image" else ""
        tag = f"_{args.resolution}_{when}" if args.kind == "video" else ""
        path = os.path.join(out, f"{args.name}{tag}{suffix}{ext}")
        req = urllib.request.Request(url)
        if urllib.parse.urlparse(url).hostname.endswith("oxen.ai"):     # only send the key to Oxen itself
            req.add_header("Authorization", f"Bearer {key}")
        with urllib.request.urlopen(req, timeout=300) as resp, open(path, "wb") as fh:
            fh.write(resp.read())
        files.append(os.path.relpath(path))
        print(f"saved {os.path.relpath(path)}")
        if args.kind == "video" and getattr(args, "aspect", None):
            cropped = path.replace(ext, f"_{args.aspect:g}{ext}")
            ffmpeg("-i", path, "-vf", f"crop='min(iw,ih*{args.aspect})':'min(ih,iw/{args.aspect})',"
                   "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                   cropped)
            files.append(os.path.relpath(cropped))
            print(f"cropped to {args.aspect:g}:1: {os.path.relpath(cropped)}")
    with open(os.path.join(out, f"{args.name}_{when}.json"), "w") as fh:
        json.dump({"request": request, "generations": records, "files": files}, fh, indent=2)
    if all(r.get("status") in DONE for r in records) and os.path.exists(pending):
        os.remove(pending)


if __name__ == "__main__":
    main()
