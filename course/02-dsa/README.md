# DSA Interview Track — Pattern-Based Course

This track takes you from basic data structures to advanced algorithms, the same way top tech companies (FAANG and similar) test candidates: by **pattern**, not by random problem. Once you recognize a pattern, you can solve dozens of "new" problems that are really the same trick wearing a different costume.

This course is language-agnostic in concept but every solution is written in **complete, runnable Python 3**. You can copy any code block into a `.py` file, or paste it into an online compiler, and run it immediately.

---

## How This Course Is Organized

Each chapter (file) follows the same structure:

1. **Concept explanation** with a diagram (ASCII or Mermaid) of the data structure or technique.
2. **When to use this pattern** — the signal words and clues in a problem statement that tell you "this is the pattern to use."
3. **Template/skeleton code** — the reusable code shape you can adapt to any problem in that pattern.
4. **6–8 problems**, ordered from basic to advanced, each with:
   - Problem statement
   - Example input/output
   - Approach explanation (in plain English)
   - Full runnable Python solution with a `if __name__ == "__main__":` test driver
   - Time and space complexity
5. **Complexity summary table**
6. **Interview tips** — how to talk through the pattern out loud in an interview.

---

## Recommended Study Order

Study the chapters in this order. Each one builds on ideas from the last.

| # | Chapter | Why this order |
|---|---------|-----------------|
| 1 | [Arrays, Strings & Hashing](01-arrays-strings-hashing.md) | Foundation of almost everything else. Hash maps show up in every later chapter. |
| 2 | [Two Pointers & Sliding Window](02-two-pointers-sliding-window.md) | Builds directly on arrays; teaches you to avoid brute-force O(n²) loops. |
| 3 | [Stack, Queue & Linked List](03-stack-queue-linkedlist.md) | Core linear data structures used inside later algorithms (e.g., BFS uses a queue). |
| 4 | [Binary Search](04-binary-search.md) | A small, sharp tool that appears inside much bigger problems later. |
| 5 | [Trees & Binary Search Trees](05-trees-bst.md) | Introduces recursion on non-linear structures — a mental model shift. |
| 6 | [Heaps & Priority Queues](06-heaps-priority-queues.md) | Needed for "top-K", scheduling, and later for Dijkstra's algorithm. |
| 7 | [Graphs](07-graphs.md) | Generalizes trees; combines BFS/DFS, Union-Find, and heaps (Dijkstra). |
| 8 | [Backtracking](08-backtracking.md) | Recursion taken further — exploring all choices, undoing wrong ones. |
| 9 | [Dynamic Programming](09-dynamic-programming.md) | The hardest and most-asked topic. Needs comfort with recursion first. |
| 10 | [Greedy & Intervals](10-greedy-intervals.md) | Contrasts with DP — teaches you when a simpler, greedy choice is enough. |
| 11 | [Tries & Bit Manipulation](11-tries-bit-manipulation.md) | Specialized tools that appear in a handful of common interview questions. |
| 12 | [Mock Interview Sets](12-mock-interview-sets.md) | Put it all together under a timer, like the real thing. |

If you only have 2–3 weeks, prioritize chapters 1–4 and 9 (arrays, two pointers, linked lists, binary search, DP) — these cover the majority of real interview questions.

---

## Big-O Cheat Sheet

### Common Time Complexities (best to worst)

| Notation | Name | Example |
|----------|------|---------|
| O(1) | Constant | Hash map lookup, array index access |
| O(log n) | Logarithmic | Binary search, balanced BST operations |
| O(n) | Linear | Single loop through an array |
| O(n log n) | Linearithmic | Efficient sorting (merge sort, heap sort), many "sort then scan" problems |
| O(n²) | Quadratic | Nested loops, brute-force pair checking |
| O(n³) | Cubic | Triple nested loops (rare in good solutions) |
| O(2ⁿ) | Exponential | Brute-force subsets, naive recursive Fibonacci |
| O(n!) | Factorial | Brute-force permutations |

### Common Data Structure Operation Costs

| Data Structure | Access | Search | Insert | Delete |
|-----------------|--------|--------|--------|--------|
| Array (unsorted) | O(1) | O(n) | O(n)* | O(n) |
| Array (sorted) | O(1) | O(log n) | O(n) | O(n) |
| Linked List | O(n) | O(n) | O(1)** | O(1)** |
| Hash Map / Set | — | O(1) avg | O(1) avg | O(1) avg |
| Stack / Queue | O(n) | O(n) | O(1) | O(1) |
| Binary Search Tree (balanced) | O(log n) | O(log n) | O(log n) | O(log n) |
| Heap (binary) | O(1) peek | O(n) | O(log n) | O(log n) |
| Trie | — | O(key length) | O(key length) | O(key length) |

\* O(1) if inserting at the end with spare capacity.
\*\* O(1) once you have a pointer to the node; finding the node still costs O(n).

### Common Sorting Algorithms

| Algorithm | Best | Average | Worst | Space | Stable? |
|-----------|------|---------|-------|-------|---------|
| Bubble Sort | O(n) | O(n²) | O(n²) | O(1) | Yes |
| Insertion Sort | O(n) | O(n²) | O(n²) | O(1) | Yes |
| Merge Sort | O(n log n) | O(n log n) | O(n log n) | O(n) | Yes |
| Quick Sort | O(n log n) | O(n log n) | O(n²) | O(log n) | No |
| Heap Sort | O(n log n) | O(n log n) | O(n log n) | O(1) | No |
| Python's `sorted()` (Timsort) | O(n) | O(n log n) | O(n log n) | O(n) | Yes |

---

## How to Practice (Running the Code)

Every problem in this course gives you complete, copy-paste-ready Python. You have three easy ways to run it:

### 1. Locally on your machine (recommended)
```bash
# Save a code block as a .py file, then run it:
python3 solution.py
```
No setup needed beyond having Python 3.10+ installed. Check with `python3 --version`.

### 2. Online compilers (zero install)
If you don't have Python installed, or you're practicing from a different device:
- **[Programiz Python Online Compiler](https://www.programiz.com/python-programming/online-compiler/)** — simplest, no sign-up needed.
- **[Replit](https://replit.com/)** — create a free Python "repl", paste code, hit Run. Good if you want to save your work across sessions.
- **[LeetCode Playground](https://leetcode.com/problemset/)** — best once you move from practicing the pattern to solving the *exact* problem on LeetCode, since it gives you the official test cases.

### 3. Mapping to LeetCode
Each problem in this course mentions the equivalent LeetCode problem (by name) where one exists. After you understand and can code the solution from scratch here, go find it on LeetCode and submit it there — this gets you used to their judge, their edge cases, and the real interview platform feel.

### Suggested practice loop for every problem
1. Read the problem statement here. Try to solve it yourself for 10–15 minutes (no peeking).
2. If stuck, read the "approach" explanation only — not the code.
3. Try again.
4. Compare with the provided solution. Type it out yourself instead of just reading it — typing builds muscle memory.
5. Run it locally or in an online compiler with the sample input to confirm it works.
6. Say the time/space complexity out loud, and explain *why*, as if an interviewer is listening.

---

## What's Next

Start with [01-arrays-strings-hashing.md](01-arrays-strings-hashing.md).

Good luck — treat this like training, not reading. The goal is to be able to *write* these solutions under pressure, not just recognize them.
