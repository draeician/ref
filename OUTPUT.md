---

### Output File Description: `references.md`

**Purpose:**  
The `references.md` file serves as a log to store URLs along with their metadata for easy reference and record-keeping. This file is located in the `references` directory within the user's home directory.

**File Location:**
```
~/references/references.md
```

**File Format:**  
Each line in the `references.md` file represents a single entry and follows a specific format:

```
{datetime}|[{url}]|({title})|{uploader or source}|{YouTube or General}
```

**Components of Each Entry:**

1. **datetime**:
   - **Format**: ISO 8601 format (`YYYY-MM-DDTHH:MM:SS`)
   - **Description**: The timestamp when the URL was added to the log.

2. **url**:
   - **Format**: Markdown link format `[URL]`
   - **Description**: The actual URL being logged. This could be a YouTube video, a YouTube playlist, or any general URL.

3. **title**:
   - **Format**: Markdown link title format `(Title)`
   - **Description**: The title of the content at the URL. For YouTube videos, this is fetched using the YouTube API. For other URLs, it is extracted from the HTML `<title>` tag of the webpage.

4. **uploader or source**:
   - **Format**: Plain text
   - **Description**: The uploader's name (for YouTube videos) or a generic source description (for other URLs).

5. **YouTube or General**:
   - **Format**: Plain text
   - **Description**: Specifies the source type. It will be either `YouTube` if the URL is a YouTube link or `General` for other types of URLs.

6. **Miscellaneous Information**:
   - **Format**: Plain text
   - **Description**: If a youtube video is specified, then the transcript file with path is specified

**Example Entries:**

1. **YouTube Video Entry:**
```
2024-05-17T14:53:10|[https://www.youtube.com/watch?v=example_id]|(Example Video Title)|ExampleUploader|YouTube|/<path>/<video id>.json
```

2. **YouTube Playlist Entry:**
```
2024-05-17T15:00:00|[https://www.youtube.com/watch?v=video1_id]|(Video 1 Title)|UploaderName|YouTube|/<path>/<video id>.json
2024-05-17T15:01:00|[https://www.youtube.com/watch?v=video2_id]|(Video 2 Title)|UploaderName|YouTube|/<path>/<video id>.json
```

3. **General URL Entry:**
```
2024-05-17T15:10:00|[https://www.example.com/article]|(Example Article Title)|ExampleSource|General
```

**Additional Information:**
- **File Integrity:** The program includes an integrity check to ensure each line in `references.md` follows the specified format. Any discrepancies are reported with the expected line format for correction.
- **Duplicate Detection:** The program checks if a URL already exists in the file before adding it. If a duplicate is found, it logs a warning and notifies the user.

---
