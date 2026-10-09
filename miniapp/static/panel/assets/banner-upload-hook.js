/* Capture selected image/video for POST /api/banners/create */
(function () {
  if (window.__lbBannerFileHook) return;
  window.__lbBannerFileHook = true;
  window.__lbLastBannerFile = null;
  document.addEventListener(
    "change",
    function (e) {
      var t = e.target;
      if (!t || t.tagName !== "INPUT" || t.type !== "file") return;
      var f = t.files && t.files[0];
      if (!f) return;
      if ((f.type || "").indexOf("image") === 0 || (f.type || "").indexOf("video") === 0) {
        window.__lbLastBannerFile = f;
      }
    },
    true
  );
})();
