function initializeQccShell() {
  const manifest =
    chrome.runtime.getManifest();

  const versionElement =
    document.getElementById(
      "qcc-version"
    );

  if (versionElement) {
    versionElement.textContent =
      `QCC ${manifest.version}`;
  }

  const buildElement =
    document.getElementById(
      "qcc-build"
    );

  if (buildElement) {
    buildElement.textContent =
      "Extension Shell";
  }
}


document.addEventListener(
  "DOMContentLoaded",
  initializeQccShell
);
