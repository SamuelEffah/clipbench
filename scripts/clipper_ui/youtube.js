// Publish to YouTube from the render dialog. Depends on app.js: $, api, toast, savePublish, publishName.
const yt = {status: null, upload: {state: "none"}, timer: 0, connecting: 0, name: "", again: false};

const ytEl = id => $(id);

function ytPaint() {
  const {status, upload} = yt;
  const uploading = upload.state === "uploading", onYouTube = upload.state === "done", done = onYouTube && !yt.again;
  setStage(done ? "done" : uploading ? "publish" : "check");
  ytEl("ytBox").classList.toggle("done", done);
  ytEl("ytHead").hidden = done;
  ytEl("ytStatus").hidden = done;
  ytEl("ytSetup").hidden = !status || status.configured;
  ytEl("ytSetupIssue").textContent = status && !status.configured ? status.message || "" : "";
  ytEl("ytBar").hidden = !uploading;
  ytEl("ytFill").style.width = `${upload.pct || 0}%`;
  ytEl("ytDisc").hidden = !(status && status.connected) || uploading || done;
  ytEl("ytLinks").hidden = !done;
  if (done) {
    ytEl("ytStudio").href = upload.studio_url;
    ytEl("ytWatch").href = upload.watch_url;
    const when = `Uploaded as ${upload.privacy || "private"}${upload.finished_at ? `, ${ago(upload.finished_at)}` : ""}`;
    ytEl("ytWhen").textContent = status.best_time ? `${when}. Best time to make it public: ${status.best_time}` : when;
    ytEl("ytTitleEcho").textContent = upload.title || "Untitled Short";
  }
  const action = ytEl("ytAction");
  action.hidden = done || !status || !status.configured;
  action.disabled = uploading;
  action.textContent = !status || !status.connected ? "Connect YouTube" : uploading ? `Uploading, ${upload.pct || 0}%` : "Upload to YouTube as unlisted";
  let text = "";
  if (!status) text = "Checking YouTube";
  else if (!status.configured) text = "Set up YouTube to upload this Short.";
  else if (!status.connected) text = "Connect your channel once. After that, Upload sends this Short to YouTube as unlisted.";
  else if (uploading) text = "Uploading. You can keep this window open.";
  else if (onYouTube) text = "This Short is already on YouTube. Uploading again creates a second video.";
  else if (upload.state === "error") text = upload.message;
  else text = "Sends the video, title and description above, with the hashtags as tags. It's unlisted until you make it public in YouTube Studio.";
  ytEl("ytStatus").textContent = text;
  ytEl("ytStatus").classList.toggle("err", upload.state === "error" && !uploading);
}

async function ytRefresh() {
  clearTimeout(yt.timer);
  if (!publishName || document.hidden) return;
  const name = publishName;
  if (yt.refreshing?.name === name) return yt.refreshing.promise;
  if (name !== yt.name) { yt.name = name; yt.again = false; yt.upload = {state: "none"}; }
  const request = {name};
  yt.refreshing = request;
  request.promise = (async () => {
    try {
      const [status, upload] = await Promise.all([api("/api/youtube?project=" + encodeURIComponent(publishName)), api(`/api/upload/${name}`)]);
      if (name !== publishName) return;
      yt.status = status;
      yt.upload = upload;
    } catch (err) {
      if (name !== publishName) return;
      yt.status = {configured: false, connected: false, message: `Couldn't reach the app: ${err.message}`};
    }
    if (document.hidden) return;
    ytPaint();
    if (yt.upload.state === "uploading") yt.timer = setTimeout(ytRefresh, 1000);
  })();
  try { await request.promise; }
  finally { if (yt.refreshing === request) yt.refreshing = null; }
}

// Uploads run on the server. Hidden tabs need no status traffic or progress paints.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(yt.timer);
  else if (publishName) return ytRefresh();
});

async function ytConnect() {
  try {
    const {url} = await api("/api/youtube/connect?project=" + encodeURIComponent(publishName), "POST", {});
    const win = window.open(url, "_blank");
    ytEl("ytStatus").textContent = win ? "Finish signing in with Google in the new tab." : "";
    if (!win) {
      ytEl("ytStatus").replaceChildren("Your browser blocked the pop-up. ", Object.assign(document.createElement("a"), {href: url, target: "_blank", rel: "noopener", textContent: "Open Google sign-in"}));
    }
    const started = Date.now(), id = ++yt.connecting;
    while (id === yt.connecting && Date.now() - started < 180000) {
      await new Promise(r => setTimeout(r, 1500));
      const status = await api("/api/youtube?project=" + encodeURIComponent(publishName)).catch(() => null);
      if (status && status.connected) {
        yt.status = status;
        ytPaint();
        return toast("YouTube connected");
      }
    }
  } catch (err) {
    toast(err.message);
  }
}

async function ytUpload() {
  try {
    clearTimeout(publishTimer);
    publishTimer = null;
    if (!(await savePublish())) return toast("Fix the title or description first. It wasn't uploaded");
    yt.again = false;
    yt.upload = await api(`/api/upload/${publishName}`, "POST", {});
    ytPaint();
    ytRefresh();
  } catch (err) {
    toast(err.message);
    ytRefresh();
  }
}

ytEl("ytAction").onclick = () => (yt.status && yt.status.connected ? ytUpload() : ytConnect());
const ytDisconnect = async () => {
  await api("/api/youtube/disconnect?project=" + encodeURIComponent(publishName), "POST", {}).catch(err => toast(err.message));
  ytRefresh();
};
ytEl("ytDisc").onclick = ytDisconnect;
ytEl("ytDiscDone").onclick = ytDisconnect;
ytEl("ytAgain").onclick = () => { yt.again = true; ytPaint(); };
