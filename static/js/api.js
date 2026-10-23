/* Thin client for the studio's Python API. All calls go to the same server that serves this page. */
(function () {
  "use strict";

  function errorFrom(res, data) {
    var msg = (data && data.error) || ("The server returned " + res.status + ".");
    var e = new Error(msg);
    e.status = res.status;
    return e;
  }

  async function parse(res) {
    var data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON body */ }
    if (!res.ok) throw errorFrom(res, data);
    return data;
  }

  async function get(path) {
    return parse(await fetch(path, { headers: { "Accept": "application/json" } }));
  }

  async function post(path, body) {
    return parse(await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body || {})
    }));
  }

  /* Sends one file as the raw request body; the server extracts its text. */
  async function upload(file) {
    return parse(await fetch("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
      body: file
    }));
  }

  /* Sends a .pptx for inventory and storage; returns slides + text. */
  async function uploadDeck(file) {
    return parse(await fetch("/api/deck/upload", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
      body: file
    }));
  }

  /* Sends a .pptx/.potx to use as an ad-hoc template; returns {template_file, name, colors}. */
  async function uploadTemplate(file) {
    return parse(await fetch("/api/template/upload", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
      body: file
    }));
  }

  /* POSTs JSON (or GETs when body is null) and saves the file the server returns.
     Resolves to { name, notice }: notice is the server's X-Studio-Notice header, or "". */
  async function download(path, body, fallbackName) {
    var res = body === null ? await fetch(path) : await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
    if (!res.ok) {
      var data = null;
      try { data = await res.json(); } catch (e) { /* ignore */ }
      throw errorFrom(res, data);
    }
    var name = fallbackName;
    var cd = res.headers.get("Content-Disposition") || "";
    var m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    if (m) name = decodeURIComponent(m[1]);
    var blob = await res.blob();
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
    return { name: name, notice: res.headers.get("X-Studio-Notice") || "" };
  }

  window.Api = { get: get, post: post, upload: upload, uploadDeck: uploadDeck, uploadTemplate: uploadTemplate, download: download };
})();
