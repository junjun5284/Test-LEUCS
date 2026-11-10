# -*- coding: utf-8 -*-
"""Re-encode the narrated deck into MP4 (video only, audio already embedded).

Kept separate from export_and_narrate.py so a crashed encode can be retried
without re-synthesising the narration.
"""
import glob
import os
import sys
import time

import win32com.client

ROOT = r"D:\浏览器\2026软件需求工程与设计模式\LEUCS_sample\harness_srs"
VIDEO = os.path.join(ROOT, "最终验收PPT语音版.mp4")


def newest_narrated():
    files = sorted(glob.glob(os.path.join(ROOT, "_voice", "narrated_*.pptx")))
    if not files:
        sys.exit("no narrated deck found")
    return files[-1]


def main():
    deck = newest_narrated()
    print("deck:", os.path.basename(deck), os.path.getsize(deck) // 1024 // 1024, "MB")

    app = win32com.client.Dispatch("PowerPoint.Application")
    pres = app.Presentations.Open(deck, ReadOnly=0, Untitled=0, WithWindow=0)
    print("slides:", pres.Slides.Count, "| transitions set:",
          pres.Slides(1).SlideShowTransition.AdvanceOnTime)

    if os.path.exists(VIDEO):
        try:
            os.remove(VIDEO)
        except OSError:
            print("old mp4 locked; will overwrite in place")

    pres.CreateVideo(VIDEO, -1, 4, 1080, 25, 80)
    print("CreateVideo started")

    started = time.time()
    last = -1
    while time.time() - started < 900:
        time.sleep(5)
        size = os.path.getsize(VIDEO) if os.path.exists(VIDEO) else 0
        try:
            status = pres.CreateVideoStatus
        except Exception as exc:  # PowerPoint died
            print("status query failed:", str(exc)[:80])
            status = None
        if size != last:
            print(f"  {time.time()-started:5.0f}s  status={status}  "
                  f"size={size/1048576:6.1f} MB")
            last = size
        if status == 3:
            print("done")
            break
        if status == 4:
            print("PowerPoint reported failure")
            break

    try:
        pres.Close()
    except Exception:
        pass
    try:
        app.Quit()
    except Exception:
        pass

    if os.path.exists(VIDEO):
        print("video:", os.path.getsize(VIDEO) / 1048576, "MB")
    else:
        print("video NOT produced")


if __name__ == "__main__":
    main()
