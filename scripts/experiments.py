import pandas as pd

df = pd.read_csv("./results.csv")

# Explosion stats
num_explosions = df["sp_explosion"].sum()
total = len(df)
explosion_rate = num_explosions / total * 100

print(f"Explosions: {num_explosions}/{total} ({explosion_rate:.1f}%)")
print(f"Avg Pred SP: {df['num_pred_sp'].mean():.2f}")
print(f"Avg Gold SP: {df['num_gold_sp'].mean():.2f}")
print(f"Avg Precision: {df['sp_precision'].mean():.4f}")
print(f"Avg Recall: {df['sp_recall'].mean():.4f}")
