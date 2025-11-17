"""
Exploratory Data Analysis (EDA) for HotpotQA Dataset

This script provides comprehensive analysis of the HotpotQA dataset including:
- Dataset statistics
- Question and answer analysis
- Context and supporting facts analysis
- Visualizations
"""

import json
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter, defaultdict
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')

# Set style for better-looking plots
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 6)


def load_hotpot(split: str = "train") -> List[Dict]:
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


def basic_statistics(data: List[Dict], split_name: str = "dataset") -> pd.DataFrame:
    """
    Compute basic statistics about the dataset.
    """
    print(f"\n{'='*60}")
    print(f"BASIC STATISTICS - {split_name.upper()}")
    print(f"{'='*60}\n")
    
    stats = {
        'Total Examples': len(data),
        'Unique Questions': len(set(ex['question'] for ex in data)),
        'Unique Answers': len(set(ex['answer'] for ex in data)),
    }
    
    # Question statistics
    question_lengths = [len(ex['question'].split()) for ex in data]
    stats['Avg Question Length (words)'] = np.mean(question_lengths)
    stats['Median Question Length (words)'] = np.median(question_lengths)
    stats['Min Question Length (words)'] = np.min(question_lengths)
    stats['Max Question Length (words)'] = np.max(question_lengths)
    
    # Answer statistics
    answer_lengths = [len(ex['answer'].split()) for ex in data]
    stats['Avg Answer Length (words)'] = np.mean(answer_lengths)
    stats['Median Answer Length (words)'] = np.median(answer_lengths)
    stats['Min Answer Length (words)'] = np.min(answer_lengths)
    stats['Max Answer Length (words)'] = np.max(answer_lengths)
    
    # Context statistics
    num_contexts = [len(ex['context']) for ex in data]
    stats['Avg Number of Context Articles'] = np.mean(num_contexts)
    stats['Median Number of Context Articles'] = np.median(num_contexts)
    stats['Min Number of Context Articles'] = np.min(num_contexts)
    stats['Max Number of Context Articles'] = np.max(num_contexts)
    
    # Supporting facts statistics
    num_supporting_facts = [len(ex.get('supporting_facts', [])) for ex in data]
    stats['Avg Number of Supporting Facts'] = np.mean(num_supporting_facts)
    stats['Median Number of Supporting Facts'] = np.median(num_supporting_facts)
    stats['Min Number of Supporting Facts'] = np.min(num_supporting_facts)
    stats['Max Number of Supporting Facts'] = np.max(num_supporting_facts)
    
    # Total sentences in context
    total_sentences = []
    for ex in data:
        total = sum(len(article[1]) for article in ex['context'])
        total_sentences.append(total)
    stats['Avg Total Sentences per Example'] = np.mean(total_sentences)
    stats['Median Total Sentences per Example'] = np.median(total_sentences)
    
    df_stats = pd.DataFrame([stats]).T
    df_stats.columns = ['Value']
    print(df_stats.to_string())
    
    return df_stats


def analyze_question_types(data: List[Dict]) -> Dict:
    """
    Analyze question types based on question words.
    """
    print(f"\n{'='*60}")
    print("QUESTION TYPE ANALYSIS")
    print(f"{'='*60}\n")
    
    question_words = ['what', 'who', 'where', 'when', 'why', 'how', 'which', 'is', 'are', 'was', 'were']
    question_type_counts = Counter()
    
    for ex in data:
        question_lower = ex['question'].lower()
        found = False
        for qw in question_words:
            if question_lower.startswith(qw):
                question_type_counts[qw] += 1
                found = True
                break
        if not found:
            question_type_counts['other'] += 1
    
    df_qtypes = pd.DataFrame(list(question_type_counts.items()), 
                            columns=['Question Type', 'Count'])
    df_qtypes['Percentage'] = (df_qtypes['Count'] / len(data) * 100).round(2)
    df_qtypes = df_qtypes.sort_values('Count', ascending=False)
    
    print(df_qtypes.to_string(index=False))
    
    return question_type_counts


def analyze_answer_types(data: List[Dict]) -> Dict:
    """
    Analyze answer types (yes/no, entity, number, etc.)
    """
    print(f"\n{'='*60}")
    print("ANSWER TYPE ANALYSIS")
    print(f"{'='*60}\n")
    
    answer_types = Counter()
    
    for ex in data:
        answer = ex['answer'].lower().strip()
        if answer in ['yes', 'no']:
            answer_types['Yes/No'] += 1
        elif answer.isdigit():
            answer_types['Number'] += 1
        elif len(answer.split()) == 1:
            answer_types['Single Word'] += 1
        elif len(answer.split()) <= 3:
            answer_types['Short Phrase (2-3 words)'] += 1
        else:
            answer_types['Long Answer'] += 1
    
    df_atypes = pd.DataFrame(list(answer_types.items()), 
                            columns=['Answer Type', 'Count'])
    df_atypes['Percentage'] = (df_atypes['Count'] / len(data) * 100).round(2)
    df_atypes = df_atypes.sort_values('Count', ascending=False)
    
    print(df_atypes.to_string(index=False))
    
    return answer_types


def analyze_supporting_facts(data: List[Dict]) -> Dict:
    """
    Analyze supporting facts distribution and patterns.
    """
    print(f"\n{'='*60}")
    print("SUPPORTING FACTS ANALYSIS")
    print(f"{'='*60}\n")
    
    num_supporting_facts = [len(ex.get('supporting_facts', [])) for ex in data]
    
    stats = {
        'Mean': np.mean(num_supporting_facts),
        'Median': np.median(num_supporting_facts),
        'Std': np.std(num_supporting_facts),
        'Min': np.min(num_supporting_facts),
        'Max': np.max(num_supporting_facts),
    }
    
    # Count distribution
    fact_count_dist = Counter(num_supporting_facts)
    df_dist = pd.DataFrame(list(fact_count_dist.items()), 
                          columns=['Number of Supporting Facts', 'Count'])
    df_dist = df_dist.sort_values('Number of Supporting Facts')
    df_dist['Percentage'] = (df_dist['Count'] / len(data) * 100).round(2)
    
    print("Supporting Facts Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value:.2f}")
    
    print("\nDistribution:")
    print(df_dist.to_string(index=False))
    
    # Analyze which articles contain supporting facts
    articles_with_supporting = []
    for ex in data:
        supporting_facts = ex.get('supporting_facts', [])
        article_titles = [fact[0] for fact in supporting_facts]
        articles_with_supporting.append(len(set(article_titles)))
    
    print(f"\nArticles with Supporting Facts:")
    print(f"  Mean: {np.mean(articles_with_supporting):.2f}")
    print(f"  Median: {np.median(articles_with_supporting):.2f}")
    print(f"  Max: {np.max(articles_with_supporting)}")
    
    return stats


def analyze_context(data: List[Dict]) -> Dict:
    """
    Analyze context articles and sentences.
    """
    print(f"\n{'='*60}")
    print("CONTEXT ANALYSIS")
    print(f"{'='*60}\n")
    
    num_articles = []
    num_sentences = []
    article_lengths = []
    
    for ex in data:
        context = ex['context']
        num_articles.append(len(context))
        
        total_sentences = 0
        for title, sentences in context:
            num_sents = len(sentences)
            total_sentences += num_sents
            article_lengths.append(num_sents)
        
        num_sentences.append(total_sentences)
    
    stats = {
        'Articles per Example': {
            'Mean': np.mean(num_articles),
            'Median': np.median(num_articles),
            'Min': np.min(num_articles),
            'Max': np.max(num_articles),
        },
        'Sentences per Example': {
            'Mean': np.mean(num_sentences),
            'Median': np.median(num_sentences),
            'Min': np.min(num_sentences),
            'Max': np.max(num_sentences),
        },
        'Sentences per Article': {
            'Mean': np.mean(article_lengths),
            'Median': np.median(article_lengths),
            'Min': np.min(article_lengths),
            'Max': np.max(article_lengths),
        }
    }
    
    for category, values in stats.items():
        print(f"{category}:")
        for key, value in values.items():
            print(f"  {key}: {value:.2f}")
        print()
    
    return stats


def create_visualizations(data: List[Dict], split_name: str = "dataset", save_dir: str = "eda_plots"):
    """
    Create comprehensive visualizations of the dataset.
    """
    os.makedirs(save_dir, exist_ok=True)
    
    print(f"\n{'='*60}")
    print(f"CREATING VISUALIZATIONS - {split_name.upper()}")
    print(f"{'='*60}\n")
    
    # Prepare data for plotting
    question_lengths = [len(ex['question'].split()) for ex in data]
    answer_lengths = [len(ex['answer'].split()) for ex in data]
    num_contexts = [len(ex['context']) for ex in data]
    num_supporting_facts = [len(ex.get('supporting_facts', [])) for ex in data]
    total_sentences = [sum(len(article[1]) for article in ex['context']) for ex in data]
    
    # 1. Question Length Distribution
    plt.figure(figsize=(12, 5))
    plt.subplot(1, 2, 1)
    plt.hist(question_lengths, bins=30, edgecolor='black', alpha=0.7)
    plt.xlabel('Question Length (words)')
    plt.ylabel('Frequency')
    plt.title('Distribution of Question Lengths')
    plt.axvline(np.mean(question_lengths), color='r', linestyle='--', 
                label=f'Mean: {np.mean(question_lengths):.1f}')
    plt.legend()
    
    plt.subplot(1, 2, 2)
    plt.boxplot(question_lengths, vert=True)
    plt.ylabel('Question Length (words)')
    plt.title('Box Plot of Question Lengths')
    plt.tight_layout()
    plt.savefig(f"{save_dir}/question_lengths_{split_name}.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Saved: question_lengths_{split_name}.png")
    
    # 2. Answer Length Distribution
    plt.figure(figsize=(12, 5))
    plt.subplot(1, 2, 1)
    plt.hist(answer_lengths, bins=30, edgecolor='black', alpha=0.7, color='orange')
    plt.xlabel('Answer Length (words)')
    plt.ylabel('Frequency')
    plt.title('Distribution of Answer Lengths')
    plt.axvline(np.mean(answer_lengths), color='r', linestyle='--', 
                label=f'Mean: {np.mean(answer_lengths):.1f}')
    plt.legend()
    
    plt.subplot(1, 2, 2)
    plt.boxplot(answer_lengths, vert=True)
    plt.ylabel('Answer Length (words)')
    plt.title('Box Plot of Answer Lengths')
    plt.tight_layout()
    plt.savefig(f"{save_dir}/answer_lengths_{split_name}.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Saved: answer_lengths_{split_name}.png")
    
    # 3. Context Articles Distribution
    plt.figure(figsize=(10, 6))
    context_counts = Counter(num_contexts)
    plt.bar(context_counts.keys(), context_counts.values(), edgecolor='black', alpha=0.7)
    plt.xlabel('Number of Context Articles')
    plt.ylabel('Frequency')
    plt.title('Distribution of Number of Context Articles per Example')
    plt.xticks(list(context_counts.keys()))
    plt.tight_layout()
    plt.savefig(f"{save_dir}/context_articles_{split_name}.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Saved: context_articles_{split_name}.png")
    
    # 4. Supporting Facts Distribution
    plt.figure(figsize=(10, 6))
    fact_counts = Counter(num_supporting_facts)
    plt.bar(fact_counts.keys(), fact_counts.values(), edgecolor='black', alpha=0.7, color='green')
    plt.xlabel('Number of Supporting Facts')
    plt.ylabel('Frequency')
    plt.title('Distribution of Number of Supporting Facts per Example')
    plt.xticks(list(fact_counts.keys()))
    plt.tight_layout()
    plt.savefig(f"{save_dir}/supporting_facts_{split_name}.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Saved: supporting_facts_{split_name}.png")
    
    # 5. Question Type Distribution
    question_words = ['what', 'who', 'where', 'when', 'why', 'how', 'which', 'is', 'are', 'was', 'were']
    question_type_counts = Counter()
    for ex in data:
        question_lower = ex['question'].lower()
        found = False
        for qw in question_words:
            if question_lower.startswith(qw):
                question_type_counts[qw] += 1
                found = True
                break
        if not found:
            question_type_counts['other'] += 1
    
    plt.figure(figsize=(12, 6))
    qtypes = list(question_type_counts.keys())
    counts = list(question_type_counts.values())
    plt.barh(qtypes, counts, edgecolor='black', alpha=0.7, color='purple')
    plt.xlabel('Frequency')
    plt.ylabel('Question Type')
    plt.title('Distribution of Question Types')
    plt.tight_layout()
    plt.savefig(f"{save_dir}/question_types_{split_name}.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Saved: question_types_{split_name}.png")
    
    # 6. Scatter Plot: Question Length vs Answer Length
    plt.figure(figsize=(10, 6))
    plt.scatter(question_lengths, answer_lengths, alpha=0.5, s=20)
    plt.xlabel('Question Length (words)')
    plt.ylabel('Answer Length (words)')
    plt.title('Question Length vs Answer Length')
    plt.tight_layout()
    plt.savefig(f"{save_dir}/question_vs_answer_length_{split_name}.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Saved: question_vs_answer_length_{split_name}.png")
    
    # 7. Total Sentences Distribution
    plt.figure(figsize=(12, 5))
    plt.subplot(1, 2, 1)
    plt.hist(total_sentences, bins=30, edgecolor='black', alpha=0.7, color='teal')
    plt.xlabel('Total Sentences per Example')
    plt.ylabel('Frequency')
    plt.title('Distribution of Total Sentences in Context')
    plt.axvline(np.mean(total_sentences), color='r', linestyle='--', 
                label=f'Mean: {np.mean(total_sentences):.1f}')
    plt.legend()
    
    plt.subplot(1, 2, 2)
    plt.boxplot(total_sentences, vert=True)
    plt.ylabel('Total Sentences per Example')
    plt.title('Box Plot of Total Sentences')
    plt.tight_layout()
    plt.savefig(f"{save_dir}/total_sentences_{split_name}.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Saved: total_sentences_{split_name}.png")
    
    # 8. Correlation Heatmap
    df_corr = pd.DataFrame({
        'Question Length': question_lengths,
        'Answer Length': answer_lengths,
        'Num Contexts': num_contexts,
        'Num Supporting Facts': num_supporting_facts,
        'Total Sentences': total_sentences
    })
    
    plt.figure(figsize=(10, 8))
    correlation_matrix = df_corr.corr()
    sns.heatmap(correlation_matrix, annot=True, fmt='.2f', cmap='coolwarm', 
                center=0, square=True, linewidths=1, cbar_kws={"shrink": 0.8})
    plt.title('Correlation Matrix of Dataset Features')
    plt.tight_layout()
    plt.savefig(f"{save_dir}/correlation_heatmap_{split_name}.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"✅ Saved: correlation_heatmap_{split_name}.png")
    
    print(f"\n✅ All visualizations saved to '{save_dir}/' directory")


def compare_splits(train_data: List[Dict], dev_data: List[Dict]):
    """
    Compare train and dev splits.
    """
    print(f"\n{'='*60}")
    print("TRAIN vs DEV COMPARISON")
    print(f"{'='*60}\n")
    
    comparisons = {
        'Total Examples': [len(train_data), len(dev_data)],
        'Avg Question Length': [
            np.mean([len(ex['question'].split()) for ex in train_data]),
            np.mean([len(ex['question'].split()) for ex in dev_data])
        ],
        'Avg Answer Length': [
            np.mean([len(ex['answer'].split()) for ex in train_data]),
            np.mean([len(ex['answer'].split()) for ex in dev_data])
        ],
        'Avg Context Articles': [
            np.mean([len(ex['context']) for ex in train_data]),
            np.mean([len(ex['context']) for ex in dev_data])
        ],
        'Avg Supporting Facts': [
            np.mean([len(ex.get('supporting_facts', [])) for ex in train_data]),
            np.mean([len(ex.get('supporting_facts', [])) for ex in dev_data])
        ],
    }
    
    df_compare = pd.DataFrame(comparisons, index=['Train', 'Dev'])
    print(df_compare.T.to_string())
    
    # Create comparison visualization
    os.makedirs("eda_plots", exist_ok=True)
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    axes = axes.flatten()
    
    metrics = list(comparisons.keys())
    train_values = [comparisons[m][0] for m in metrics]
    dev_values = [comparisons[m][1] for m in metrics]
    
    x = np.arange(len(metrics))
    width = 0.35
    
    for i, metric in enumerate(metrics):
        ax = axes[i]
        bars1 = ax.bar(x[i] - width/2, train_values[i], width, label='Train', alpha=0.8)
        bars2 = ax.bar(x[i] + width/2, dev_values[i], width, label='Dev', alpha=0.8)
        ax.set_ylabel('Value')
        ax.set_title(metric)
        ax.legend()
        ax.set_xticks([])
    
    plt.tight_layout()
    plt.savefig("eda_plots/train_dev_comparison.png", dpi=300, bbox_inches='tight')
    plt.close()
    print(f"\n✅ Saved: train_dev_comparison.png")


def main():
    """
    Main function to run all EDA analyses.
    """
    print("\n" + "="*60)
    print("HOTPOTQA DATASET - EXPLORATORY DATA ANALYSIS")
    print("="*60)
    
    # Load datasets
    print("\n📊 Loading datasets...")
    train_data = load_hotpot("train")
    dev_data = load_hotpot("dev")
    
    # Analyze train split
    print("\n" + "="*60)
    print("ANALYZING TRAIN SPLIT")
    print("="*60)
    basic_statistics(train_data, "train")
    analyze_question_types(train_data)
    analyze_answer_types(train_data)
    analyze_supporting_facts(train_data)
    analyze_context(train_data)
    create_visualizations(train_data, "train")
    
    # Analyze dev split
    print("\n" + "="*60)
    print("ANALYZING DEV SPLIT")
    print("="*60)
    basic_statistics(dev_data, "dev")
    analyze_question_types(dev_data)
    analyze_answer_types(dev_data)
    analyze_supporting_facts(dev_data)
    analyze_context(dev_data)
    create_visualizations(dev_data, "dev")
    
    # Compare splits
    compare_splits(train_data, dev_data)
    
    print("\n" + "="*60)
    print("EDA COMPLETE! ✅")
    print("="*60)
    print("\nAll visualizations have been saved to the 'eda_plots/' directory.")


if __name__ == "__main__":
    main()

