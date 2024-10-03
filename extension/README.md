
# Copy Tab URLs Browser Extension

## Overview

The "Copy Tab URLs" browser extension allows users to quickly copy the URLs of all open tabs to the clipboard with a single click. This extension is compatible with both Chrome and Firefox.

## Features

- Copies URLs of all open tabs to the clipboard
- Simple and minimalistic design
- No popup; URLs are copied directly when the extension icon is clicked

## Installation

### Chrome

1. Clone or download this repository.
2. Open Chrome and go to `chrome://extensions/`.
3. Enable "Developer mode" by toggling the switch in the top right corner.
4. Click on "Load unpacked" and select the folder containing the extension files.

### Firefox

1. Clone or download this repository.
2. Open Firefox and go to `about:debugging#/runtime/this-firefox`.
3. Click on "Load Temporary Add-on" and select the `manifest.json` file in the extension folder.

## Usage

1. Click the extension icon in the browser toolbar.
2. The URLs of all open tabs will be copied to the clipboard.
3. Paste the copied URLs into any document or text editor.

## Files

- `manifest.json`: Defines the extension properties and permissions.
- `background.js`: Handles the logic for copying URLs to the clipboard when the extension icon is clicked.
- `icons/`: Contains the icon images used for the extension.

## Development

### Prerequisites

- Node.js (for development tooling, if needed)
- A text editor (such as VSCode)

### Building

No build steps are required for this simple extension. Just ensure all necessary files are in place as per the folder structure:

```
extension_folder/
│
├── icons/
│   ├── icon16.png
│   ├── icon48.png
│   └── icon128.png
│
├── manifest.json
└── background.js
```

### Testing

1. Make sure the extension is loaded in your browser as described in the Installation section.
2. Open multiple tabs.
3. Click the extension icon.
4. Verify that the URLs are copied to the clipboard and can be pasted into a text editor.

## Contributing

1. Fork the repository.
2. Create a new branch (`git checkout -b feature/your-feature-name`).
3. Make your changes.
4. Commit your changes (`git commit -m 'Add some feature'`).
5. Push to the branch (`git push origin feature/your-feature-name`).
6. Open a pull request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgements

Thanks to the creators of the tools and libraries used in this project.

## Contact

For any inquiries or issues, please open an issue in this repository.
