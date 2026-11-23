// 点扩展图标就开侧栏；快捷键 Alt+Shift+A 也行
function setup() {
  chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}).catch(() => {});
}
chrome.runtime.onInstalled.addListener(setup);
chrome.runtime.onStartup.addListener(setup);
setup();

chrome.commands.onCommand.addListener(async (cmd) => {
  if (cmd !== "open-panel") return;
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (tab) await chrome.sidePanel.open({tabId: tab.id});
  } catch (e) {}
});