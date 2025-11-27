Embedding files (GloVe)

This folder is intended to hold pre-trained embedding files such as GloVe.

Why here?
- Large binary/text embedding files belong in `data/` with other dataset assets, not in the repository root.

What you should do
1. Move any large files from the repo root into this folder. For example:
   mv ~/hotpotqa/glove.840B.300d.txt ~/hotpotqa/data/embeddings/
   mv ~/hotpotqa/glove.840B.300d.zip ~/hotpotqa/data/embeddings/

2. If you prefer, run the provided downloader script from `data/hotpotqa`:
   cd data/hotpotqa && bash download.sh

Notes
- I did not move or delete your large GloVe files automatically to avoid data loss.
- The project code reads embeddings from wherever your configuration points to. If you change the location, update the config or environment variables accordingly.

If you'd like, I can also update scripts/configs to point to this new location automatically (I already updated `data/hotpotqa/download.sh`).
