#!/usr/bin/env python3
"""Generate still images on fal.ai (design references, style frames), with a cost check first.

Usage:
  python3 scripts/fal_image.py --prompt "..." --out DIR [--name car] [--count 2] [--size landscape_16_9]
      [--width 2240 --height 960] [--ref-image car.png ...] [--seed 1] [--max-cost 0.5] [--yes]
      [--resume REQUEST_ID]

Uses fal-ai/bytedance/seedream/v4/text-to-image, or .../v4/edit when --ref-image is given (up to 10
reference images, e.g. a character and a location, to compose a shot's start frame). Priced per
image. --width/--height set a custom size (area at least 921,600 px). Without --yes it only prints
the estimate. Saves <out>/<name>_1.png ... and a JSON log. Needs FAL_KEY in the environment.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fal_video import data_uri, queue_urls, submit_and_wait, unit_price, wait  # noqa: E402

TEXT_ENDPOINT = "fal-ai/bytedance/seedream/v4/text-to-image"
EDIT_ENDPOINT = "fal-ai/bytedance/seedream/v4/edit"


def main():
    sys.stdout.reconfigure(line_buffering=True)      # progress shows up in logs as it happens
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--name", default="image")
    parser.add_argument("--count", type=int, default=1, help="images to generate (1-6)")
    parser.add_argument("--size", default="landscape_16_9")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--ref-image", action="append", default=[], help="reference image (switches to the edit model)")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--max-cost", type=float, default=0.5)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--resume", metavar="REQUEST_ID", help="collect an already-submitted request (no new job)")
    args = parser.parse_args()

    key = os.environ.get("FAL_KEY")
    if not key:
        sys.exit("FAL_KEY is not set")
    endpoint = EDIT_ENDPOINT if args.ref_image else TEXT_ENDPOINT
    size = {"width": args.width, "height": args.height} if args.width and args.height else args.size
    for ref in args.ref_image:
        if not os.path.exists(ref):
            sys.exit(f"missing reference image {ref}")
    price, unit = unit_price(endpoint, key)
    cost = price * args.count
    print(f"model:    {endpoint}")
    print(f"images:   {args.count} x {size}")
    for ref in args.ref_image:
        print(f"          reference image {ref}")
    print(f"estimate: ${cost:.2f}  (${price}/{unit})")
    out = os.path.abspath(args.out)
    if args.resume:
        pending = os.path.join(out, f"pending_{args.resume}.json")
        if os.path.exists(pending):
            with open(pending) as fh:
                rec = json.load(fh)
            status_url, response_url = rec["status_url"], rec["response_url"]
        else:
            status_url, response_url = queue_urls(endpoint, args.resume)
        print(f"resuming request {args.resume} (no new job is submitted)")
        request_id, result = wait(status_url, response_url, args.resume, key)
        return save(args, endpoint, cost, out, request_id, result)
    if not args.yes:
        print("dry run: nothing sent. Add --yes to submit.")
        return
    if cost > args.max_cost:
        sys.exit(f"estimate ${cost:.2f} is over --max-cost ${args.max_cost:.2f}; not submitting")

    os.makedirs(out, exist_ok=True)
    payload = {"prompt": args.prompt, "image_size": size, "num_images": args.count}
    if args.ref_image:
        payload["image_urls"] = [data_uri(r, "image/png" if r.lower().endswith(".png") else "image/jpeg")
                                 for r in args.ref_image]
    if args.seed is not None:
        payload["seed"] = args.seed
    request_id, result = submit_and_wait(endpoint, payload, key, out)
    save(args, endpoint, cost, out, request_id, result)


def save(args, endpoint, cost, out, request_id, result):
    files = []
    for i, image in enumerate(result.get("images", []), start=1):
        path = os.path.join(out, f"{args.name}_{i}.png")
        urllib.request.urlretrieve(image["url"], path)
        files.append(os.path.relpath(path))
        print(f"saved {os.path.relpath(path)} ({image.get('width')}x{image.get('height')})")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(out, f"{args.name}_{stamp}.json"), "w") as fh:
        json.dump({"model": endpoint, "request_id": request_id, "prompt": args.prompt, "seed": result.get("seed"),
                   "ref_images": args.ref_image,
                   "estimate_usd": round(cost, 3), "files": files}, fh, indent=2)
    pending = os.path.join(out, f"pending_{request_id}.json")
    if os.path.exists(pending):
        os.remove(pending)


if __name__ == "__main__":
    main()
