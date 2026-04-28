# MagicLight Auto — Google Sheets Structure

The Google Sheet acts as the database for the entire automation pipeline. 
The script automatically reads the column matching below. 

### Columns Structure (Exactly 21 Columns)

| Column | Name             | Description                                                                                     |
|:------:|:-----------------|:------------------------------------------------------------------------------------------------|
| **A**  | `Status`         | The current status. Set to `Pending` to queue it. The script changes this to `Done` or `Error`. |
| **B**  | `Theme`          | (Optional) Theme of the story.                                                                  |
| **C**  | `Title`          | (Optional) The folder name and video will be derived from this.                                 |
| **D**  | `Story`          | **(Required)** The main story text to be generated into a video.                                |
| **E**  | `Moral`          | (Optional) A moral constraint to provide to the generator.                                      |
| **F**  | `Gen_Title`      | Output field: The AI-generated title downloaded from MagicLight.                                |
| **G**  | `Gen_Summary`    | Output field: The short summary generated for the video description.                            |
| **H**  | `Gen_Tags`       | Output field: AI-generated hashtags.                                                            |
| **I**  | `Project_URL`    | Output field: URL pointing back to the project on MagicLight.                                   |
| **J**  | `Created_Time`   | Output field: Timestamp when the script started processing the story.                           |
| **K**  | `Completed_Time` | Output field: Timestamp when the video generation finally completed.                            |
| **L**  | `Notes`          | Output field: Detailed logs, tracebacks, or credit usage reports.                               |
| **M**  | `Drive_Link`     | Output field: The Google Drive preview link for the un-processed original render.               |
| **N**  | `DriveImg_Link`  | Output field: Preview link for the extracted thumbnail image.                                   |
| **O**  | `Credit_Before`  | Output field: The user's credit balance before generating.                                      |
| **P**  | `Credit_After`   | Output field: The user's credit balance after generation completing.                            |
| **Q**  | `Email_Used`     | Output field: Which account from `accounts.txt` was used for processing.                        |
| **R**  | `Credit_Acct`    | Extra field                                                                                     |
| **S**  | `Credit_Total`   | Extra field                                                                                     |
| **T**  | `Credit_Used`    | Extra field                                                                                     |
| **U**  | `Credit_Remaining` | Extra field                                                                                   |

## How to Initialize
1. Open your specified Google Sheet.
2. In `main.py`, you can run `python main.py --migrate-schema` in your terminal to automatically place these exact 21 headers directly into row 1.
3. Paste a story in column `D` and set column `A` to `Pending`. 
