import json
import os

def load_hotpot(split="train"):
    """
    Loads the HotpotQA dataset.
    Args:
        split (str): 'train' or 'dev' to choose which split to load.
    Returns:
        data (list): List of QA examples (each a dictionary).
    """

    base_path = "data/hotpotqa"
    file_map = {
        "train": "hotpot_train_v1.1.json",
        "dev": "hotpot_dev_distractor_v1.json"
    }

    file_path = os.path.join(base_path, file_map[split])

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset file not found at {file_path}")

    with open(file_path, "r") as f:
        data = json.load(f)

    print(f"✅ Loaded {len(data):,} {split} examples from {file_path}")
    return data


def preview_example(example, show_context=True):
    """
    Prints one example in a readable way.
    """
    print("\n============================")
    print(f"ID: {example['_id']}")
    print(f"Question: {example['question']}")
    print(f"Answer: {example['answer']}")
    print(f"Supporting Facts: {example.get('supporting_facts', [])}")

    if show_context:
        print("\nContext Articles:")
        for title, sentences in example['context'][:2]:  # show first 2
            print(f"  - {title}: {sentences[0][:150]}...")
    print("============================\n")


def main():
    # 1️⃣ Load training data
    train_data = load_hotpot("train")

    # 2️⃣ Load dev data
    dev_data = load_hotpot("dev")

    # 3️⃣ Preview the first example
    print("\n--- First Training Example ---")
    preview_example(train_data[0])

    print("\n--- First Dev Example ---")
    preview_example(dev_data[0])


if __name__ == "__main__":
    main()
