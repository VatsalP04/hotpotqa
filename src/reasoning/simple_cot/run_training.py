import argparse
from .train import train_probes


def main():
    parser = argparse.ArgumentParser(description="Train probes for SimpleCoT")
    parser.add_argument("--model_name", type=str, default="meta-llama/Llama-3.1-8B-Instruct",
                        help="Model name to use")
    parser.add_argument("--data_dir", type=str, default="data/hotpotqa",
                        help="Directory containing HotpotQA data")
    parser.add_argument("--train_size", type=int, default=28000,
                        help="Number of training examples")
    parser.add_argument("--val_size", type=int, default=7000,
                        help="Number of validation examples")
    parser.add_argument("--batch_size", type=int, default=4,
                        help="Batch size")
    parser.add_argument("--num_epochs", type=int, default=3,
                        help="Number of epochs")
    parser.add_argument("--learning_rate", type=float, default=1e-4,
                        help="Learning rate")
    parser.add_argument("--output_dir", type=str, default="outputs/simple_cot",
                        help="Output directory")
    parser.add_argument("--save_interval", type=int, default=100,
                        help="Save interval for intermediate results")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed")
    
    args = parser.parse_args()
    
    train_probes(
        model_name=args.model_name,
        data_dir=args.data_dir,
        train_size=args.train_size,
        val_size=args.val_size,
        batch_size=args.batch_size,
        num_epochs=args.num_epochs,
        learning_rate=args.learning_rate,
        output_dir=args.output_dir,
        save_interval=args.save_interval,
        seed=args.seed
    )


if __name__ == "__main__":
    main()

