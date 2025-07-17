# XamarinBlober
XamarinBlober is a tool for unpacking and repacking `assemblies.blob` files used in Xamarin applications.

Unlike [pyxamstore](https://github.com/USDev/XamarinStoreExtractor), XamarinBlober **successfully repacks** the blob, and also **extracts additional useful files** such as:

- `.pdb` (debug symbols)
- `.dll.config` (configuration files)
## Installation
```
pip install -r requirements.txt
```
## Usage
#### Unpack
```
python xamarinBlober.py unpack assemblies.blob assemblies.manifest extracted_files/
```
#### Repack
```
python xamarinBlober.py pack assemblies.blob assemblies.manifest extracted_files/
```
## Files
- `xamarinBlober.py` – The main script for extracting and repacking blobs.
- `requirements.txt` – Dependencies (uses `lz4==1.1.0`).
- `lyze_assemblies.blob.txt` – Notes and structure analysis of the `assemblies.blob` format.

## Credits
Thanks to pyxamstore repository I was able to jump directly to the source code and understand faster the format.
