async function configureSidePanel() {
  if (!chrome.sidePanel) {
    return;
  }

  try {
    await chrome.sidePanel.setPanelBehavior({
      openPanelOnActionClick: true
    });
  } catch (error) {
    console.error(
      "[QCC] No se pudo configurar Side Panel:",
      error
    );
  }
}


chrome.runtime.onInstalled.addListener(() => {
  configureSidePanel();
});


chrome.runtime.onStartup.addListener(() => {
  configureSidePanel();
});


configureSidePanel();
