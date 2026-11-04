#!/usr/bin/env python3
"""End-to-end test of the skill's scripts on synthetic files (used by CI on Mac, Windows, Linux).

    python3 tests/run_pipeline.py [workdir]
"""
import json, os, shutil, subprocess, sys, tempfile
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SK = os.path.join(ROOT, "skills", "instagram-skill")
S = os.path.join(SK, "scripts")
PY = sys.executable


def run(*args, ok=(0,)):
    print("$", " ".join(os.path.basename(a) if os.sep in a else a for a in args), flush=True)
    r = subprocess.run([PY, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-3000:], r.stderr[-2000:], sep="")
    if r.returncode not in ok:
        sys.exit(f"FAILED ({r.returncode}): {args[0]}")
    return r


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def main():
    work = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
    os.makedirs(work, exist_ok=True)
    os.chdir(work)
    from PIL import Image, ImageDraw
    os.makedirs("in", exist_ok=True)
    im = Image.new("RGBA", (1200, 1600), (30, 120, 200, 255))
    ImageDraw.Draw(im).ellipse([300, 500, 900, 1100], fill=(255, 200, 0, 255))
    im.save("in/tall.png")
    Image.new("RGB", (4000, 2000), (200, 80, 60)).save("in/wide.jpg", quality=92)
    ff("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=50", "-f", "lavfi", "-i", "sine=frequency=440",
       "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv444p", "-c:a", "libopus", "in/land.mkv")
    ff("-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30", "-f", "lavfi", "-i", "sine=frequency=330",
       "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", "in/ok.mp4")

    run(os.path.join(S, "check_setup.py"))
    shutil.copy(os.path.join(SK, "examples", "water-week", "bottle-en.json"), "slides.json")
    os.makedirs("media", exist_ok=True)
    shutil.copy(os.path.join(SK, "examples", "water-week", "media", "earth.jpg"), "media/earth.jpg")
    run(os.path.join(S, "render_slides.py"), "slides.json", "--out", "slides")
    assert len([f for f in os.listdir("slides") if f.startswith("slide-")]) == 6
    story = json.load(open("slides.json"))
    story["theme"]["ratio"] = "9:16"
    story["slides"] = [{"type": "text", "title": "A question?", "body": "Answer on the feed.", "alt": "x"}]
    json.dump(story, open("story.json", "w"))
    run(os.path.join(S, "render_slides.py"), "story.json", "--out", "story")
    with Image.open("story/slide-01.jpg") as im:
        assert im.size == (1080, 1920), im.size

    plan = {
        "brand": {"handle": "@test"}, "timezone": "Europe/Amsterdam",
        "accounts": {"a": {"handle": "@a", "socialAccountId": "1", "timezone": "America/New_York", "times": ["12:30"]},
                     "b": {"handle": "@b", "socialAccountId": "2", "timezone": "Europe/Madrid", "times": ["13:30"]}},
        "posts": [
            {"id": "car", "format": "carousel", "media": ["slides/slide-01.jpg", "slides/slide-02.jpg", "in/tall.png"],
             "caption": "Hook line\n\n#a #b #c #d #e #f", "targets": [{"account": "a"}, {"account": "b"}]},
            {"id": "pic", "format": "image", "media": ["in/wide.jpg"], "caption": "A picture", "targets": [{"account": "a"}]},
            {"id": "reel", "format": "reel", "media": ["in/land.mkv"], "caption": "A reel", "targets": [{"account": "a"}], "trial": "MANUAL"},
            {"id": "story", "format": "story", "media": ["story/slide-01.jpg"], "with": {"post": "car", "minutes": -60},
             "targets": [{"account": "a"}]},
        ],
    }
    json.dump(plan, open("plan.json", "w"))
    r = run(os.path.join(S, "ig_check.py"), "plan.json", ok=(1,))
    for must in ("6 hashtags", "only takes JPEG", "taller than 4:5", "wider than 1.91:1", "MP4 or MOV", "AAC", "9:16",
                 "repost of the first"):
        assert must in r.stdout, f"missing check: {must}"
    r = run(os.path.join(S, "ig_check.py"), "plan.json", "--fix", ok=(1,))  # hashtags + landscape Reel stay errors
    assert "lose" in r.stdout and "frame" in r.stdout, "landscape Reel must not be padded automatically"
    p = json.load(open("plan.json"))
    p["posts"][2]["frame"] = {"title": "A framed Reel headline"}
    p["posts"][2]["own_footage"] = True
    p["posts"][0]["targets"][1]["media"] = ["slides/slide-02.jpg", "slides/slide-01.jpg", p["posts"][0]["media"][2]]
    json.dump(p, open("plan.json", "w"))
    run(os.path.join(S, "ig_check.py"), "plan.json", "--fix", ok=(1,))  # the hashtag error stays
    p = json.load(open("plan.json"))
    p["posts"][0]["caption"] = "Hook line\n\n#a #b #c"
    p["posts"][0]["targets"][1]["caption"] = "Another hook\n\n#a"
    json.dump(p, open("plan.json", "w"))
    run(os.path.join(S, "ig_check.py"), "plan.json")
    with Image.open(p["posts"][0]["media"][2]) as im:
        assert im.format == "JPEG" and abs(im.width / im.height - 0.8) < 0.01, im.size
    with Image.open(p["posts"][3]["media"][0]) as im:
        assert im.size == (1080, 1920), im.size
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,pix_fmt",
                          "-of", "csv=p=0", p["posts"][2]["media"][0]], capture_output=True, text=True).stdout
    assert "h264,1080,1920,yuv420p" in out and "aac" in out, out

    run(os.path.join(S, "reel.py"), "frames", "in/ok.mp4", "--out", "reel", "--n", "4")
    run(os.path.join(S, "reel.py"), "cover", "in/ok.mp4", "--at", "1.5", "--title", "Three rules", "--out", "reel/cover.jpg")
    run(os.path.join(S, "reel.py"), "zones", "in/ok.mp4", "--out", "reel/zones.jpg")
    for f in ("reel/frames-sheet.jpg", "reel/cover.jpg", "reel/cover-grid.jpg", "reel/zones.jpg"):
        assert os.path.getsize(f) > 1000, f
    with Image.open("reel/cover.jpg") as im:
        assert im.size == (1080, 1920)

    start = (date.today() + timedelta(days=3)).isoformat()
    run(os.path.join(S, "schedule.py"), "plan.json", "--start", start, "--times", "09:00,18:00", "--skip", "sun")
    p = json.load(open("plan.json"))
    ats = [t["at"] for post in p["posts"] for t in post["targets"]]
    assert all(ats), ats
    car = p["posts"][0]["targets"]
    assert car[0]["at"].endswith("12:30") and car[1]["at"].endswith("13:30"), car  # each account's own time
    st = p["posts"][3]["targets"][0]["at"]
    assert st.endswith("11:30") and st[:10] == car[0]["at"][:10], st  # the Story an hour before its post
    body = json.load(open(os.path.join("requests", "reel-a.json")))
    assert body["socialAccounts"][0]["postType"] == "REEL" and body["socialAccounts"][0]["trialParams"]["graduationStrategy"] == "MANUAL"
    assert body["schedule"]["scheduledFor"].endswith("Z")
    assert json.load(open(os.path.join("requests", "story-a.json")))["socialAccounts"][0]["postType"] == "STORY"

    run(os.path.join(S, "preview.py"), "plan.json", "--out", "preview")
    assert os.path.getsize("preview/index.html") > 2000 and os.path.getsize("preview/preview.png") > 10000

    # results: 7 carousels on account a, posted 9 to 21 days ago, numbers collected over time
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hist_posts = []
    for n in range(7):
        posted = (now - timedelta(days=9 + 2 * n)).replace(tzinfo=None)
        hist_posts.append({"id": f"c{n}", "format": "carousel", "media": ["slides/slide-01.jpg"],
                           "caption": f"Post {n}", "targets": [{"account": "a", "at": posted.isoformat(timespec="minutes"), "postId": f"w{n}"}]})
    p["posts"] = hist_posts
    json.dump(p, open("plan.json", "w"))
    run(os.path.join(S, "log.py"), "record", "plan.json")
    items = []
    for n, post in enumerate(hist_posts):
        posted = datetime.fromisoformat(post["targets"][0]["at"]).replace(tzinfo=timezone.utc)
        def series(base):
            return [{"value": base // 3, "collectedAt": (posted + timedelta(days=1)).isoformat()},
                    {"value": base, "collectedAt": (posted + timedelta(days=7)).isoformat()},
                    {"value": base * 2, "collectedAt": (posted + timedelta(days=30)).isoformat()}]
        items.append({"postId": f"w{n}", "socialAccountId": "1",
                      "analytics": {"uniqueImpressions": series(1000 + 100 * n), "shares": series(5 + 3 * n), "saves": series(20 - n)}})
    json.dump({"socialAccountPosts": items}, open("metrics.json", "w"))
    r = run(os.path.join(S, "log.py"), "results", "--metrics", "metrics.json")
    assert "7 ranked of 7" in r.stdout and "Best carousel" in r.stdout and "w6" not in r.stdout, r.stdout
    assert "c6:" in r.stdout.split("| Post |")[1].split("\n")[2], "highest shares per reach should rank first"
    logged = [json.loads(x) for x in open("posts.jsonl")]
    assert all(abs(x["measured"]["reach"]["age"] - 7) < 0.1 for x in logged), "day-7 values must be kept"
    print("\nALL PIPELINE CHECKS PASSED")


if __name__ == "__main__":
    main()
