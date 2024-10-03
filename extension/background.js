chrome.browserAction.onClicked.addListener(() => {
  chrome.windows.getCurrent({populate: true}, (currentWindow) => {
    const tabs = currentWindow.tabs;
    if (chrome.runtime.lastError) {
      console.error(chrome.runtime.lastError);
      alert('Failed to query tabs.');
      return;
    }
    const urls = tabs.map(tab => tab.url).join('\n');
    copyToClipboard(urls);
  });
});

function copyToClipboard(text) {
  const textarea = document.createElement('textarea');
  textarea.value = ''; // Clear the clipboard first
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy'); // Blank the clipboard

  textarea.value = text;
  textarea.select();
  try {
    const successful = document.execCommand('copy');
    if (successful) {
      alert('URLs copied to clipboard!');
    } else {
      console.error('Failed to copy text.');
      alert('Failed to copy URLs to clipboard.');
    }
  } catch (err) {
    console.error('Error copying to clipboard: ', err);
    alert('Error copying to clipboard.');
  }
  document.body.removeChild(textarea);
}

