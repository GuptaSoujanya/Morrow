# Chapter 5: Trees & Binary Search Trees

## 1. Concept

A **binary tree** is a node-based structure where each node has at most two children (`left` and `right`). A **binary search tree (BST)** adds a rule: for every node, all values in its left subtree are smaller, and all values in its right subtree are larger.

```
Binary Tree:                 Binary Search Tree:
        5                            5
       / \                          / \
      3   8                        3   8
     / \   \                      / \   \
    1   4   9                    1   4   9

BST property at every node:
  left subtree < node < right subtree
```

Most tree problems are solved with **recursion**: a function that processes the current node, then calls itself on `left` and `right`, trusting that those calls will correctly solve the smaller sub-problem (this trust is called "assuming the recursive case works" — the same idea as mathematical induction).

## 2. When to Use This Pattern

- Input is explicitly a tree or BST.
- "Depth", "height", "balanced", "path from root to leaf" → tree recursion (DFS).
- "Level by level" / "shortest path in an unweighted tree" → BFS (level-order traversal with a queue).
- "k-th smallest", "is it a valid BST", "insert/delete while keeping sorted order" → BST properties.
- Problems that give you two trees to compare → recursion on both trees simultaneously.

## 3. Template / Skeleton Code

```python
from collections import deque


class TreeNode:
    def __init__(self, val: int = 0, left: "TreeNode | None" = None, right: "TreeNode | None" = None):
        self.val = val
        self.left = left
        self.right = right


def dfs_template(node: TreeNode | None):
    if node is None:
        return  # base case
    # process node.val here (preorder: before recursing)
    dfs_template(node.left)
    dfs_template(node.right)
    # (postorder: process node.val here instead, after recursing)


def bfs_template(root: TreeNode | None) -> list[list[int]]:
    if root is None:
        return []
    result = []
    queue = deque([root])
    while queue:
        level_size = len(queue)
        level_values = []
        for _ in range(level_size):
            node = queue.popleft()
            level_values.append(node.val)
            if node.left:
                queue.append(node.left)
            if node.right:
                queue.append(node.right)
        result.append(level_values)
    return result
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Maximum Depth of Binary Tree
**Statement:** Given the root of a binary tree, return its maximum depth (number of nodes along the longest path from root to a leaf).

**Example:**
```
Input:     3
          / \
         9  20
            /  \
           15   7
Output: 3
```

**Approach:** The depth of a tree is 1 (for the current node) plus the larger of the depths of its left and right subtrees. This is a one-line recursive definition once you trust the recursive calls.

```python
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


def max_depth(root: TreeNode | None) -> int:
    if root is None:
        return 0
    return 1 + max(max_depth(root.left), max_depth(root.right))


if __name__ == "__main__":
    root = TreeNode(3, TreeNode(9), TreeNode(20, TreeNode(15), TreeNode(7)))
    print(max_depth(root))  # 3
    print(max_depth(None))  # 0
```

**Complexity:** Time O(n) — visits every node once. Space O(h) for the recursion stack, where h is the tree height (worst case O(n) for a skewed tree).

---

### Problem 2: Invert Binary Tree
**Statement:** Given the root of a binary tree, swap every left and right child (mirror the tree) and return the new root.

**Example:**
```
Input:      4                Output:     4
           / \                          / \
          2   7                        7   2
         / \ / \                      / \ / \
        1  3 6  9                    9  6 3  1
```

**Approach:** Recursively invert the left and right subtrees, then swap the two children pointers at the current node.

```python
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


def invert_tree(root: TreeNode | None) -> TreeNode | None:
    if root is None:
        return None
    root.left, root.right = invert_tree(root.right), invert_tree(root.left)
    return root


def to_level_list(root: TreeNode | None) -> list:
    from collections import deque
    if root is None:
        return []
    result, queue = [], deque([root])
    while queue:
        node = queue.popleft()
        if node is None:
            result.append(None)
            continue
        result.append(node.val)
        queue.append(node.left)
        queue.append(node.right)
    while result and result[-1] is None:
        result.pop()
    return result


if __name__ == "__main__":
    root = TreeNode(4, TreeNode(2, TreeNode(1), TreeNode(3)), TreeNode(7, TreeNode(6), TreeNode(9)))
    inverted = invert_tree(root)
    print(to_level_list(inverted))  # [4, 7, 2, 9, 6, 3, 1]
```

**Complexity:** Time O(n), Space O(h).

---

### Problem 3: Same Tree
**Statement:** Given the roots of two binary trees, determine if they are structurally identical and have the same node values.

**Example:**
```
Input: p = [1, 2, 3], q = [1, 2, 3]
Output: True
```

**Approach:** Two trees are the same if: both are `None` (base case, match), or both are non-`None`, have equal values, AND their left subtrees match each other AND their right subtrees match each other.

```python
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


def is_same_tree(p: TreeNode | None, q: TreeNode | None) -> bool:
    if p is None and q is None:
        return True
    if p is None or q is None:
        return False
    if p.val != q.val:
        return False
    return is_same_tree(p.left, q.left) and is_same_tree(p.right, q.right)


if __name__ == "__main__":
    p = TreeNode(1, TreeNode(2), TreeNode(3))
    q = TreeNode(1, TreeNode(2), TreeNode(3))
    print(is_same_tree(p, q))  # True

    r = TreeNode(1, TreeNode(2))
    print(is_same_tree(p, r))  # False
```

**Complexity:** Time O(n), Space O(h).

---

### Problem 4: Binary Tree Level Order Traversal
**Statement:** Given the root of a binary tree, return its level-order traversal (values grouped by depth, left to right).

**Example:**
```
Input:     3
          / \
         9  20
            /  \
           15   7
Output: [[3], [9, 20], [15, 7]]
```

**Approach:** This is BFS using a queue. Process nodes level by level: track how many nodes are currently in the queue (that's the current level's size), pop exactly that many, collect their values, and push their children for the next level.

```python
from collections import deque


class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


def level_order(root: TreeNode | None) -> list[list[int]]:
    if root is None:
        return []

    result = []
    queue = deque([root])

    while queue:
        level_size = len(queue)
        level_values = []
        for _ in range(level_size):
            node = queue.popleft()
            level_values.append(node.val)
            if node.left:
                queue.append(node.left)
            if node.right:
                queue.append(node.right)
        result.append(level_values)

    return result


if __name__ == "__main__":
    root = TreeNode(3, TreeNode(9), TreeNode(20, TreeNode(15), TreeNode(7)))
    print(level_order(root))  # [[3], [9, 20], [15, 7]]
```

**Complexity:** Time O(n), Space O(n) (queue can hold up to one full level, worst case O(n) for a wide tree).

---

### Problem 5: Validate Binary Search Tree
**Statement:** Given the root of a binary tree, determine if it is a valid BST.

**Example:**
```
Input:     5
          / \
         1   4
            / \
           3   6
Output: False   # 4's left child (3) is fine, but 4 is in 5's right subtree and 4 < ... wait, check: 3 < 5 is fine, but node 4's right child 6 > 5 is fine too. The real violation: 4's left child 3 must be > 4? No — violation is actually that node value 3 < 4 but also must be > 5 since it's in 5's right subtree. 3 is not > 5, so invalid.
```

**Approach:** A common bug is only checking `node.left.val < node.val < node.right.val` locally — this misses violations from grandparents. Instead, pass down a valid `(low, high)` range for each node as you recurse: every node must satisfy `low < node.val < high`. When going left, the new `high` becomes the current node's value. When going right, the new `low` becomes the current node's value.

```python
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


def is_valid_bst(root: TreeNode | None) -> bool:
    def validate(node: TreeNode | None, low: float, high: float) -> bool:
        if node is None:
            return True
        if not (low < node.val < high):
            return False
        return validate(node.left, low, node.val) and validate(node.right, node.val, high)

    return validate(root, float("-inf"), float("inf"))


if __name__ == "__main__":
    valid = TreeNode(5, TreeNode(1), TreeNode(4, TreeNode(3), TreeNode(6)))
    print(is_valid_bst(valid))  # False (3 is in 5's right subtree but 3 < 5)

    good = TreeNode(5, TreeNode(3), TreeNode(8))
    print(is_valid_bst(good))  # True
```

**Complexity:** Time O(n), Space O(h).

---

### Problem 6: Kth Smallest Element in a BST
**Statement:** Given the root of a BST and an integer `k`, return the k-th smallest value in it.

**Example:**
```
Input:     3
          / \
         1   4
          \
           2
k = 1
Output: 1
```

**Approach:** An **in-order traversal** (left, node, right) of a BST visits nodes in sorted ascending order. So the k-th smallest is simply the k-th value visited during an in-order traversal. We can stop early once we've counted `k` values.

```python
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


def kth_smallest(root: TreeNode | None, k: int) -> int:
    stack = []
    node = root

    while stack or node:
        while node:
            stack.append(node)
            node = node.left

        node = stack.pop()
        k -= 1
        if k == 0:
            return node.val

        node = node.right

    return -1  # k was larger than number of nodes


if __name__ == "__main__":
    root = TreeNode(3, TreeNode(1, None, TreeNode(2)), TreeNode(4))
    print(kth_smallest(root, 1))  # 1
    print(kth_smallest(root, 3))  # 3
```

**Complexity:** Time O(h + k) — in the worst case O(n) if `k` is close to n. Space O(h) for the explicit stack.

---

### Problem 7: Lowest Common Ancestor of a Binary Search Tree
**Statement:** Given a BST and two nodes `p` and `q` that exist in the tree, find their lowest common ancestor (the deepest node that has both `p` and `q` as descendants, where a node can be its own ancestor).

**Example:**
```
Input:      6
          /   \
         2     8
        / \   / \
       0   4 7   9
p = 2, q = 8
Output: 6
```

**Approach:** Use the BST property instead of generic tree LCA logic. Starting at the root: if both `p` and `q` are smaller than the current node, the LCA must be in the left subtree. If both are larger, it must be in the right subtree. Otherwise (one is smaller or equal and the other is larger or equal), the current node is the split point — the LCA.

```python
class TreeNode:
    def __init__(self, val=0, left=None, right=None):
        self.val = val
        self.left = left
        self.right = right


def lowest_common_ancestor(root: TreeNode, p: TreeNode, q: TreeNode) -> TreeNode:
    node = root
    while node:
        if p.val < node.val and q.val < node.val:
            node = node.left
        elif p.val > node.val and q.val > node.val:
            node = node.right
        else:
            return node
    return None


if __name__ == "__main__":
    n0, n4, n7, n9 = TreeNode(0), TreeNode(4), TreeNode(7), TreeNode(9)
    n2 = TreeNode(2, n0, n4)
    n8 = TreeNode(8, n7, n9)
    root = TreeNode(6, n2, n8)

    result = lowest_common_ancestor(root, n2, n8)
    print(result.val)  # 6

    result2 = lowest_common_ancestor(root, n2, n4)
    print(result2.val)  # 2
```

**Complexity:** Time O(h) — h is tree height, O(log n) for balanced, O(n) worst case for skewed. Space O(1) (iterative version).

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Maximum Depth of Binary Tree | O(n) | O(h) |
| Invert Binary Tree | O(n) | O(h) |
| Same Tree | O(n) | O(h) |
| Binary Tree Level Order Traversal | O(n) | O(n) |
| Validate Binary Search Tree | O(n) | O(h) |
| Kth Smallest Element in a BST | O(h + k) | O(h) |
| Lowest Common Ancestor of a BST | O(h) | O(1) |

---

## 6. Interview Tips

- **State the base case first, out loud.** For every tree recursion, say "my base case is when the node is `None`" before writing any code. This is the #1 thing interviewers check for, and skipping it causes crashes.
- **Trust the recursion.** When writing something like `max_depth`, explicitly say: "I'll assume `max_depth(root.left)` correctly returns the depth of the left subtree — I don't need to re-derive how recursion works each time, I just need to combine the sub-results correctly at this level."
- **Know DFS vs BFS by name and when to pick each.** DFS (recursion or explicit stack) is natural for "path" or "subtree" questions. BFS (queue) is natural for "level" or "shortest path in unweighted structure" questions. Say which one you're choosing and why.
- **For BST problems, always ask "can I use the sorted property?"** before writing generic tree code. Problems 5, 6, and 7 above are all dramatically simpler because of the BST ordering — missing this turns an O(log n)/O(n) elegant solution into unnecessarily complex code.
- **Mention height vs. balanced explicitly if relevant.** Recursion stack depth is O(h), not O(log n), unless the tree is balanced. If asked about worst-case space, say: "If the tree is skewed into a linked-list shape, h becomes n, so the worst-case space is O(n)."
