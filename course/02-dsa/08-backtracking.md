# Chapter 8: Backtracking

## 1. Concept

Backtracking is organized trial-and-error: you build a solution piece by piece, and whenever a partial solution can't possibly lead to a valid answer, you **undo the last choice** ("backtrack") and try a different one. It's DFS over a tree of *choices*, not over a physical data structure.

```
Exploring subsets of [1, 2, 3]:

                        []
          /             |             \
        [1]            [2]            [3]
       /    \            \
    [1,2]  [1,3]        [2,3]
      |
   [1,2,3]

At each node: "include this element or not?"
If a branch violates a rule, backtrack (go back up) and try the next option.
```

The universal backtracking shape:
1. **Choose** — pick an option.
2. **Explore** — recurse deeper with that choice made.
3. **Un-choose** — undo the choice before trying the next option (this is the "backtrack" step).

## 2. When to Use This Pattern

- "Generate all possible X" (subsets, permutations, combinations) → backtracking.
- "Find all valid arrangements satisfying constraints" (N-Queens, Sudoku) → backtracking.
- Problem says "return all solutions," not just "does a solution exist" or "the best solution."
- Input size is small (often ≤ 20) — a hint that an exponential-time exploration is expected and acceptable.
- You can describe the problem as "try an option, recurse, undo, try the next option."

## 3. Template / Skeleton Code

```python
def backtrack_template(choices: list, path: list, results: list) -> None:
    if is_complete(path):
        results.append(path[:])  # copy! path will keep changing
        return

    for choice in choices:
        if not is_valid(choice, path):
            continue

        path.append(choice)       # choose
        backtrack_template(choices, path, results)  # explore
        path.pop()                 # un-choose (backtrack)


def is_complete(path: list) -> bool:
    return False  # placeholder


def is_valid(choice, path: list) -> bool:
    return True  # placeholder
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Subsets
**Statement:** Given an array of unique integers, return all possible subsets (the power set).

**Example:**
```
Input: nums = [1, 2, 3]
Output: [[], [1], [2], [1,2], [3], [1,3], [2,3], [1,2,3]]  (any order)
```

**Approach:** At each element, we have exactly two choices: include it in the current subset, or don't. Explore both branches recursively. When we've made a decision for every element, the current path is a complete subset — record it.

```python
def subsets(nums: list[int]) -> list[list[int]]:
    results: list[list[int]] = []
    path: list[int] = []

    def backtrack(start: int) -> None:
        results.append(path[:])  # every path along the way is a valid subset

        for i in range(start, len(nums)):
            path.append(nums[i])
            backtrack(i + 1)
            path.pop()

    backtrack(0)
    return results


if __name__ == "__main__":
    result = subsets([1, 2, 3])
    for subset in result:
        print(subset)
    # [], [1], [1, 2], [1, 2, 3], [1, 3], [2], [2, 3], [3]
```

**Complexity:** Time O(n · 2ⁿ) — there are 2ⁿ subsets, each taking O(n) to copy. Space O(n) for recursion depth (excluding output).

---

### Problem 2: Permutations
**Statement:** Given an array of unique integers, return all possible permutations (orderings).

**Example:**
```
Input: nums = [1, 2, 3]
Output: [[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]]
```

**Approach:** Build the permutation one position at a time. At each step, try every number that hasn't been used yet. When the path's length equals `len(nums)`, it's a complete permutation.

```python
def permute(nums: list[int]) -> list[list[int]]:
    results: list[list[int]] = []
    path: list[int] = []
    used = [False] * len(nums)

    def backtrack() -> None:
        if len(path) == len(nums):
            results.append(path[:])
            return

        for i in range(len(nums)):
            if used[i]:
                continue
            used[i] = True
            path.append(nums[i])
            backtrack()
            path.pop()
            used[i] = False

    backtrack()
    return results


if __name__ == "__main__":
    result = permute([1, 2, 3])
    for p in result:
        print(p)
    # [1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]
```

**Complexity:** Time O(n · n!) — n! permutations, each O(n) to build/copy. Space O(n) for recursion depth.

---

### Problem 3: Combination Sum
**Statement:** Given an array of candidate numbers (can be reused unlimited times) and a target, return all unique combinations that sum to the target.

**Example:**
```
Input: candidates = [2, 3, 6, 7], target = 7
Output: [[2,2,3], [7]]
```

**Approach:** At each step, try each candidate from the current starting index onward (not from 0 — this avoids generating the same combination in different orders, like `[2,3,2]` vs `[2,2,3]`). Since candidates can repeat, allow re-choosing the *same* index again (pass `i`, not `i + 1`, in the recursive call). Stop a branch early if the remaining target goes negative.

```python
def combination_sum(candidates: list[int], target: int) -> list[list[int]]:
    results: list[list[int]] = []
    path: list[int] = []

    def backtrack(start: int, remaining: int) -> None:
        if remaining == 0:
            results.append(path[:])
            return
        if remaining < 0:
            return

        for i in range(start, len(candidates)):
            path.append(candidates[i])
            backtrack(i, remaining - candidates[i])  # reuse same index allowed
            path.pop()

    backtrack(0, target)
    return results


if __name__ == "__main__":
    result = combination_sum([2, 3, 6, 7], 7)
    for combo in result:
        print(combo)
    # [2, 2, 3]
    # [7]
```

**Complexity:** Time O(2^target) worst case (exponential branching), Space O(target) for recursion depth.

---

### Problem 4: Word Search
**Statement:** Given an `m x n` grid of characters and a word, determine if the word can be formed by sequentially adjacent cells (horizontally/vertically), using each cell at most once.

**Example:**
```
Input: board = [["A","B","C","E"],
                 ["S","F","C","S"],
                 ["A","D","E","E"]], word = "ABCCED"
Output: True
```

**Approach:** Try starting the search from every cell matching the word's first letter. From there, DFS in all 4 directions, matching one letter of the word at a time. Mark cells as "in use" temporarily (backtracking!) so the same cell isn't reused within one path, then un-mark it when that path doesn't pan out.

```python
def exist(board: list[list[str]], word: str) -> bool:
    rows, cols = len(board), len(board[0])

    def backtrack(r: int, c: int, index: int) -> bool:
        if index == len(word):
            return True
        if (r < 0 or r >= rows or c < 0 or c >= cols
                or board[r][c] != word[index]):
            return False

        temp = board[r][c]
        board[r][c] = "#"  # mark as visited/used

        found = (backtrack(r + 1, c, index + 1)
                 or backtrack(r - 1, c, index + 1)
                 or backtrack(r, c + 1, index + 1)
                 or backtrack(r, c - 1, index + 1))

        board[r][c] = temp  # un-mark (backtrack)
        return found

    for r in range(rows):
        for c in range(cols):
            if backtrack(r, c, 0):
                return True
    return False


if __name__ == "__main__":
    board = [
        ["A", "B", "C", "E"],
        ["S", "F", "C", "S"],
        ["A", "D", "E", "E"],
    ]
    print(exist(board, "ABCCED"))  # True
    print(exist(board, "SEE"))      # True
    print(exist(board, "ABCB"))     # False
```

**Complexity:** Time O(rows × cols × 4^L) where L is the word length (worst case branching). Space O(L) for recursion depth.

---

### Problem 5: Palindrome Partitioning
**Statement:** Given a string, partition it so that every substring is a palindrome. Return all possible partitions.

**Example:**
```
Input: s = "aab"
Output: [["a","a","b"], ["aa","b"]]
```

**Approach:** At each position, try every possible "next cut" — if the substring from the current start to that cut is a palindrome, recurse on the rest of the string with that piece added to the path. If we reach the end of the string, the path is a valid full partition.

```python
def partition(s: str) -> list[list[str]]:
    results: list[list[str]] = []
    path: list[str] = []

    def is_palindrome(sub: str) -> bool:
        return sub == sub[::-1]

    def backtrack(start: int) -> None:
        if start == len(s):
            results.append(path[:])
            return

        for end in range(start + 1, len(s) + 1):
            substring = s[start:end]
            if is_palindrome(substring):
                path.append(substring)
                backtrack(end)
                path.pop()

    backtrack(0)
    return results


if __name__ == "__main__":
    result = partition("aab")
    for p in result:
        print(p)
    # ['a', 'a', 'b']
    # ['aa', 'b']
```

**Complexity:** Time O(n · 2ⁿ) worst case (2ⁿ possible partitions, each needing O(n) palindrome checks). Space O(n) for recursion depth.

---

### Problem 6: N-Queens
**Statement:** Place `n` queens on an `n x n` chessboard so that no two queens attack each other (same row, column, or diagonal). Return the count of distinct solutions.

**Example:**
```
Input: n = 4
Output: 2
```

**Approach:** Place queens one row at a time. For each row, try every column; a placement is valid if no other queen already placed shares that column or either diagonal. Use sets to track used columns and diagonals in O(1): note that all cells on the same "/" diagonal share the value `row + col`, and all cells on the same "\" diagonal share `row - col`.

```python
def total_n_queens(n: int) -> int:
    cols_used: set[int] = set()
    diag1_used: set[int] = set()  # row + col
    diag2_used: set[int] = set()  # row - col
    count = 0

    def backtrack(row: int) -> None:
        nonlocal count
        if row == n:
            count += 1
            return

        for col in range(n):
            if col in cols_used or (row + col) in diag1_used or (row - col) in diag2_used:
                continue

            cols_used.add(col)
            diag1_used.add(row + col)
            diag2_used.add(row - col)

            backtrack(row + 1)

            cols_used.remove(col)
            diag1_used.remove(row + col)
            diag2_used.remove(row - col)

    backtrack(0)
    return count


if __name__ == "__main__":
    print(total_n_queens(4))  # 2
    print(total_n_queens(1))  # 1
    print(total_n_queens(8))  # 92
```

**Complexity:** Time O(n!) worst case (pruned heavily in practice by the column/diagonal checks). Space O(n) for the sets and recursion depth.

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Subsets | O(n · 2ⁿ) | O(n) |
| Permutations | O(n · n!) | O(n) |
| Combination Sum | O(2^target) worst case | O(target) |
| Word Search | O(rows·cols·4^L) | O(L) |
| Palindrome Partitioning | O(n · 2ⁿ) | O(n) |
| N-Queens | O(n!) worst case | O(n) |

---

## 6. Interview Tips

- **Describe the choose/explore/un-choose cycle explicitly.** Say: "I add this element to my path, recurse, and then remove it before trying the next option — that removal step is what makes this 'backtracking' instead of plain recursion." This is the single sentence that proves you understand the pattern, not just the code shape.
- **Always mention why you copy the path (`path[:]`) when recording results.** A very common bug is appending the *same* mutable list object to results repeatedly, so all recorded answers end up looking identical after later mutations. Say this out loud to avoid the bug and to show awareness.
- **Talk about pruning before writing the loop.** For Combination Sum and N-Queens, explain your pruning condition up front ("if remaining target goes negative, stop exploring this branch") — pruning is usually the actual optimization interviewers want to see, not just "try everything."
- **Acknowledge the exponential time complexity honestly.** Don't hide from O(2ⁿ) or O(n!) — say: "This problem inherently requires exploring an exponential number of possibilities since we need *all* valid answers, so this time complexity is expected, not a sign of an inefficient solution."
- **For grid-based backtracking (Word Search), mention the in-place marking trick.** Say: "Instead of a separate `visited` set, I temporarily overwrite the cell's value during the DFS and restore it afterward — this saves space without changing behavior." This small detail often impresses interviewers focused on space optimization.
