import json
import os
import logging
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from tqdm import tqdm
import numpy as np
from collections import Counter

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src import get_agent
from src.core.orchestrator import DebateOrchestrator

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

DATA_DIR = "data"
PLOTS_DIR = "plots"
os.makedirs(PLOTS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

plt.style.use('default')
plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['font.size'] = 10
plt.rcParams['axes.grid'] = True
plt.rcParams['grid.alpha'] = 0.3


def check_correctness(judge_agent, system_answer: str, correct_answer: str) -> bool:
    system_prompt = (
        "You are an impartial answer grader. Compare the system's answer with the ground truth.\n"
        "Answers are considered correct if they are semantically equivalent, even if formatted differently.\n"
        "For example:\n"
        "  - '153' and '153.0' are equivalent\n"
        "  - 'Solver_3' and 'solver 3' are equivalent\n"
        "  - '42' and 'forty-two' are equivalent\n\n"
        "Reply with ONLY a single word: 'YES' if correct, 'NO' if incorrect.\n"
        "Do not include any explanation or additional text."
    )
    
    user_prompt = (
        f"Ground Truth: {correct_answer}\n"
        f"System Answer: {system_answer}\n\n"
        f"Are these answers equivalent?"
    )
    
    try:
        response = judge_agent.generate(
            system_prompt, 
            user_prompt, 
            temperature=0.0
        )
        
        cleaned_response = response.strip().upper()
        if "YES" in cleaned_response:
            return True
        elif "NO" in cleaned_response:
            return False
        else:
            return str(system_answer).strip().lower() == str(correct_answer).strip().lower()
            
    except Exception as e:
        return str(system_answer).strip().lower() == str(correct_answer).strip().lower()


def get_majority_answer(answers: list) -> str:
    """Helper to find the majority answer among the 3 initial solutions for the voting baseline."""
    if not answers:
        return "ERROR"
    # Normalize strings for voting
    norm_answers = [str(a).strip().lower() for a in answers]
    counts = Counter(norm_answers)
    majority_norm = counts.most_common(1)[0][0]
    
    # Return the original case answer that matches the majority
    for a in answers:
        if str(a).strip().lower() == majority_norm:
            return a
    return answers[0]


def check_consensus(answers: list) -> bool:
    """Helper to check if all 3 solvers reached the same answer in Stage 3."""
    if len(answers) < 3:
        return False
    norm_answers = [str(a).strip().lower() for a in answers]
    return len(set(norm_answers)) == 1


def create_plots(df):
    # 1. Confidence Distribution
    plt.figure(figsize=(10, 6))
    correct_conf = df[df["is_correct"]]["confidence"]
    incorrect_conf = df[~df["is_correct"]]["confidence"]
    
    plt.hist(correct_conf, bins=10, alpha=0.6, label=f"correct (n={len(correct_conf)})", color="#10b981", edgecolor='black')
    plt.hist(incorrect_conf, bins=10, alpha=0.6, label=f"incorrect (n={len(incorrect_conf)})", color="#ef4444", edgecolor='black')
    
    plt.xlabel("Judge Confidence", fontsize=12, fontweight='bold')
    plt.ylabel("Count", fontsize=12, fontweight='bold')
    plt.title("Confidence Distribution by Correctness", fontsize=14, fontweight='bold')
    plt.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(f"{PLOTS_DIR}/1_confidence_distribution.png")
    plt.close()
 
    # 2. Accuracy by Category
    if len(df) > 1 and 'category' in df.columns:
        fig, ax = plt.subplots(figsize=(10, 6))
        category_stats = df.groupby('category').agg({'is_correct': ['mean', 'count']}).reset_index()
        category_stats.columns = ['category', 'accuracy', 'count']
        category_stats['accuracy'] = category_stats['accuracy'] * 100
        
        colors = ['#10b981' if acc >= 50 else '#ef4444' for acc in category_stats['accuracy']]
        bars = ax.bar(category_stats['category'], category_stats['accuracy'], color=colors, alpha=0.7, edgecolor='black')
    
        for bar, count in zip(bars, category_stats['count']):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 2,
                   f'n={int(count)}', ha='center', va='bottom', fontsize=9)
        
        ax.set_ylabel("Accuracy (%)", fontsize=12, fontweight='bold')
        ax.set_xlabel("Category", fontsize=12, fontweight='bold')
        ax.set_title("Accuracy by Problem Category", fontsize=14, fontweight='bold')
        ax.set_ylim(0, 110)
        ax.axhline(y=50, color='gray', linestyle='--', alpha=0.5, label='50% threshold')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        plt.savefig(f"{PLOTS_DIR}/2_accuracy_by_category.png")
        plt.close()
       
    # 3. Winner Distribution
    if len(df) > 1:
        plt.figure(figsize=(10, 6))
        winner_counts = df['winner_role'].value_counts()
        colors = plt.cm.Set3(np.linspace(0, 1, len(winner_counts)))
        
        plt.pie(winner_counts.values, labels=winner_counts.index, autopct='%1.1f%%',
               colors=colors, startangle=90, textprops={'fontsize': 10, 'fontweight': 'bold'})
        plt.title("Distribution of Winning Solvers", fontsize=14, fontweight='bold', pad=20)
        plt.tight_layout()
        plt.savefig(f"{PLOTS_DIR}/3_winner_distribution.png")
        plt.close()

    # 4. NEW REQUIRED PLOT: Baselines vs Full System
    if len(df) > 0:
        plt.figure(figsize=(9, 6))
        baselines = ['Single LLM', 'Majority Vote\n(No Debate)', 'Full Debate\nSystem']
        accuracies = [
            df['single_llm_correct'].mean() * 100,
            df['voting_correct'].mean() * 100,
            df['is_correct'].mean() * 100
        ]
        colors = ['#3b82f6', '#f59e0b', '#10b981']
        
        bars = plt.bar(baselines, accuracies, color=colors, edgecolor='black', alpha=0.8)
        
        for bar in bars:
            height = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2., height + 1.5,
                     f'{height:.1f}%', ha='center', va='bottom', fontweight='bold', fontsize=12)
                     
        plt.title('Performance Comparison: Baselines vs Full System', fontsize=14, fontweight='bold')
        plt.ylabel('Accuracy (%)', fontsize=12, fontweight='bold')
        plt.ylim(0, max(accuracies) + 15)  # Leave room for labels
        plt.tight_layout()
        plt.savefig(f"{PLOTS_DIR}/4_baseline_comparison.png")
        plt.close()


def evaluate_and_plot():
    agents = {
        "gemini_1": get_agent("gemini"),
        "gemini_2": get_agent("gemini"),
        "gemini_3": get_agent("gemini"),
        "gemini_4": get_agent("gemini"),
    }

    orchestrator = DebateOrchestrator(agents)
    grader_agent = agents["gemini_1"]

    with open(f"{DATA_DIR}/input_problems.json", "r") as f:
        problems = json.load(f)

    results = []

    for problem in tqdm(problems, desc="Evaluating problems"):
        problem_id = problem["id"]
        question = problem["question"]
        correct_answer = problem["correct_answer"]
        category = problem["category"]
        
        print(f"\n{'='*50}")
        print(f"PROBLEM {problem_id}: {category}")
        print(f"{'='*50}")
        
        try:
            verdict, history = orchestrator.run_full_debate(question)
            
            # Extract Stage 1 (Initial) and Stage 3 (Refined) answers
            s1_solutions = history.get("stage_1_solutions", {})
            s3_solutions = history.get("stage_3_refined", {})
            
            s1_answers = [sol.refined_answer for sol in s1_solutions.values()]
            s3_answers = [sol.refined_answer for sol in s3_solutions.values()]
            
            # --- CALCULATE METRICS AND BASELINES ---
            
            # 1. Full System Correctness
            is_correct = check_correctness(grader_agent, verdict.winning_answer, correct_answer)
            
            # 2. Single-LLM Baseline (Just evaluate the first solver's initial answer)
            single_llm_answer = s1_answers[0] if s1_answers else "ERROR"
            single_llm_correct = check_correctness(grader_agent, single_llm_answer, correct_answer)
            
            # 3. Simple Voting Baseline (Majority vote of Stage 1 answers)
            voting_answer = get_majority_answer(s1_answers)
            voting_correct = check_correctness(grader_agent, voting_answer, correct_answer)
            
            # 4. Consensus Rate
            has_consensus = check_consensus(s3_answers)
            
            # 5. Improvement Rate (Failed single LLM, but Full System got it right)
            improved = (not single_llm_correct) and is_correct
            
            # 6. Judge Accuracy on Disagreement
            solvers_disagreed = not has_consensus
            judge_saved_the_day = solvers_disagreed and is_correct
            
            results.append({
                "id": problem_id,
                "category": category,
                "question": question,
                "correct_answer": correct_answer,
                "system_answer": verdict.winning_answer,
                "winner_role": verdict.winner,
                "confidence": verdict.confidence,
                "is_correct": is_correct,
                "single_llm_correct": single_llm_correct,
                "voting_correct": voting_correct,
                "improved": improved,
                "has_consensus": has_consensus,
                "solvers_disagreed": solvers_disagreed,
                "judge_saved_the_day": judge_saved_the_day,
                "judge_reasoning": verdict.reasoning,
            })
            
        except Exception as e:
            print(f"ERROR processing problem {problem_id}: {e}") 
            results.append({
                "id": problem_id,
                "category": category,
                "question": question,
                "correct_answer": correct_answer,
                "system_answer": "ERROR",
                "winner_role": "Error",
                "confidence": 0.0,
                "is_correct": False,
                "single_llm_correct": False,
                "voting_correct": False,
                "improved": False,
                "has_consensus": False,
                "solvers_disagreed": False,
                "judge_saved_the_day": False,
                "judge_reasoning": str(e),
            })

    # Save RAW results
    with open(f"{DATA_DIR}/results_raw.json", "w") as f:
        json.dump(results, f, indent=2)

    # --- PRINT FINAL PHASE 3 METRICS ---
    df = pd.DataFrame(results)
    
    print('\n' + '='*50)
    print('FINAL PHASE 3 EVALUATION RESULTS')
    print('='*50)
    print(f"Total Problems: {len(results)}")
    print(f"Correct (Full System): {df['is_correct'].sum()}")
    print(f"Incorrect (Full System): {(~df['is_correct']).sum()}")
    print(f"Average Judge Confidence: {df['confidence'].mean():.3f}\n")
    
    print("--- BASELINE COMPARISONS ---")
    print(f"1. Single-LLM Accuracy:  {df['single_llm_correct'].mean() * 100:.1f}%")
    print(f"2. Simple Voting Accuracy: {df['voting_correct'].mean() * 100:.1f}%")
    print(f"3. Full System Accuracy: {df['is_correct'].mean() * 100:.1f}%\n")
    
    print("--- SYSTEM METRICS ---")
    print(f"Consensus Rate (All 3 agreed): {df['has_consensus'].mean() * 100:.1f}%")
    print(f"Improvement Count (Refinement fixed initial failure): {df['improved'].sum()} problems")
    
    disagreements = df['solvers_disagreed'].sum()
    if disagreements > 0:
        judge_acc = (df['judge_saved_the_day'].sum() / disagreements) * 100
        print(f"Judge Accuracy (When solvers disagreed): {judge_acc:.1f}% ({df['judge_saved_the_day'].sum()}/{disagreements} times)")
    else:
        print("Judge Accuracy (When solvers disagreed): N/A (Solvers always agreed)")
    
    if len(df) > 0:
        print("\n--- ACCURACY BY CATEGORY ---")
        category_accuracy = df.groupby('category')['is_correct'].agg(['mean', 'count'])
        category_accuracy['mean'] = category_accuracy['mean'] * 100
        category_accuracy.columns = ['Accuracy (%)', 'Count']
        print(category_accuracy)
    
    # Generate Plots
    create_plots(df)
    print(f"\nAll plots saved to ./{PLOTS_DIR}/")


if __name__ == "__main__":
    evaluate_and_plot()