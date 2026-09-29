# Video Downloader

A free browser based video downloader for individual public Instagram, YouTube, and TikTok links. It uses [yt-dlp](https://github.com/yt-dlp/yt-dlp), Deno, and FFmpeg. Download only videos you own or have permission to save.

## Put it online for free

This repository is ready for [Render](https://render.com/) using its free web service plan. The included `render.yaml` and `Dockerfile` install the server and video tools.

1. Create a free Render account with your GitHub account.
2. In Render, choose **New → Blueprint**, connect this GitHub repository, and apply the `render.yaml` blueprint. Select the free plan if asked.
3. Wait for the deploy to finish and open the `onrender.com` URL that Render gives you.

The website provides a link field, progress display, and a **Save video** button. It accepts one video at a time and limits files to 100 MB. It cannot use your browser's login cookies, so private or login gated videos may fail. The free Render service sleeps after 15 minutes of inactivity, and the first visit after that can take about a minute to start. Some sites may block requests from cloud servers. Render's free usage and bandwidth limits also apply.

## Run the website locally

Python 3.11 or newer and FFmpeg are recommended. Install the dependencies in `web/requirements.txt`, then run:

```sh
uvicorn server:app --app-dir web --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`.

## Optional Windows desktop app

The original desktop app remains in `app.py`. Double-click **Start Downloader.cmd** to install its local dependencies and open it. Downloads go to `Downloads\Video Downloader` by default. If a site changes, run **Update Downloader.cmd**. For public videos, leave **Browser login** at **None**. Chrome's Windows cookie encryption can prevent yt-dlp from reading a Chrome session; Firefox may work for videos that require login.
