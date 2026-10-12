# Chapter 3: Stack, Queue & Linked List

## 1. Concept

A **stack** is Last-In-First-Out (LIFO): the most recently added item is the first one removed. Think of a stack of plates.

A **queue** is First-In-First-Out (FIFO): the earliest added item is the first one removed. Think of a line at a coffee shop.

A **linked list** is a chain of nodes, where each node holds a value and a pointer to the next node. Unlike arrays, there's no contiguous memory block — you must follow pointers to traverse it.

```
Stack (LIFO):                 Queue (FIFO):
  push -> [ C ]  <- pop         enqueue -> [A][B][C] -> dequeue
          [ B ]
          [ A ]

Linked List:
 head -> [1 | next] -> [2 | next] -> [3 | next] -> None
```

## 2. When to Use This Pattern

- "Matching pairs" (parentheses, brackets, tags) → **stack**.
- "Undo" operations, DFS implemented iteratively, evaluating expressions → **stack**.
- "Process in the order received", BFS traversal, scheduling → **queue** (or `collections.deque`).
- Problems that explicitly mention "linked list," "reverse a list in-place," "detect a cycle," or "merge lists" → **linked list** techniques (often combined with two pointers — slow/fast runners).
- "Next greater/smaller element" problems → **monotonic stack**.

## 3. Template / Skeleton Code

```python
from collections import deque

class ListNode:
    def __init__(self, val: int = 0, next: "ListNode | None" = None):
        self.val = val
        self.next = next


def stack_template(s: str) -> bool:
    stack: list[str] = []
    for char in s:
        if char in "([{":
            stack.append(char)
        else:
            if not stack:
                return False
            stack.pop()
    return not stack


def queue_bfs_template(start):
    queue = deque([start])
    visited = {start}
    while queue:
        node = queue.popleft()
        # process node
        for neighbor in []:  # neighbors of node
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)


def linked_list_reverse_template(head: ListNode | None) -> ListNode | None:
    prev = None
    current = head
    while current:
        next_node = current.next
        current.next = prev
        prev = current
        current = next_node
    return prev
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Valid Parentheses
**Statement:** Given a string containing just `(`, `)`, `{`, `}`, `[`, `]`, determine if the input is valid — every opening bracket has a matching, correctly-ordered closing bracket.

**Example:**
```
Input: s = "()[]{}"
Output: True

Input: s = "(]"
Output: False
```

**Approach:** Push every opening bracket onto a stack. When you see a closing bracket, it must match the bracket on top of the stack (the most recently opened one) — pop and compare. If it doesn't match, or the stack is empty when you need to pop, the string is invalid. At the end, the stack must be empty (no unclosed brackets).

```python
def is_valid(s: str) -> bool:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []

    for char in s:
        if char in "([{":
            stack.append(char)
        else:
            if not stack or stack.pop() != pairs[char]:
                return False

    return not stack


if __name__ == "__main__":
    print(is_valid("()[]{}"))  # True
    print(is_valid("(]"))       # False
    print(is_valid("([)]"))     # False
    print(is_valid("{[]}"))     # True
```

**Complexity:** Time O(n), Space O(n).

---

### Problem 2: Implement Queue Using Stacks
**Statement:** Implement a FIFO queue using only two stacks.

**Example:**
```
queue = MyQueue()
queue.push(1)
queue.push(2)
queue.peek()    # 1
queue.pop()     # 1
queue.empty()   # False
```

**Approach:** Use an "in" stack for pushes, and an "out" stack for pops/peeks. When the "out" stack is empty and we need to pop/peek, transfer everything from "in" to "out" — this reverses the order, turning LIFO into FIFO. Transfers are amortized O(1) per operation because each element is moved at most once between the two stacks.

```python
class MyQueue:
    def __init__(self):
        self.stack_in: list[int] = []
        self.stack_out: list[int] = []

    def push(self, x: int) -> None:
        self.stack_in.append(x)

    def _transfer_if_needed(self) -> None:
        if not self.stack_out:
            while self.stack_in:
                self.stack_out.append(self.stack_in.pop())

    def pop(self) -> int:
        self._transfer_if_needed()
        return self.stack_out.pop()

    def peek(self) -> int:
        self._transfer_if_needed()
        return self.stack_out[-1]

    def empty(self) -> bool:
        return not self.stack_in and not self.stack_out


if __name__ == "__main__":
    q = MyQueue()
    q.push(1)
    q.push(2)
    print(q.peek())    # 1
    print(q.pop())     # 1
    print(q.empty())   # False
    print(q.pop())     # 2
    print(q.empty())   # True
```

**Complexity:** Time O(1) amortized per operation, Space O(n).

---

### Problem 3: Reverse Linked List
**Statement:** Given the head of a singly linked list, reverse the list and return the new head.

**Example:**
```
Input: 1 -> 2 -> 3 -> 4 -> 5 -> None
Output: 5 -> 4 -> 3 -> 2 -> 1 -> None
```

**Approach:** Walk through the list once, and for every node, flip its `next` pointer to point backward instead of forward. Keep three pointers: `prev` (the new "next" target), `current` (the node being processed), and a temporary to remember `current.next` before we overwrite it.

```python
class ListNode:
    def __init__(self, val: int = 0, next: "ListNode | None" = None):
        self.val = val
        self.next = next


def reverse_list(head: ListNode | None) -> ListNode | None:
    prev = None
    current = head
    while current:
        next_node = current.next
        current.next = prev
        prev = current
        current = next_node
    return prev


def build_list(values: list[int]) -> ListNode | None:
    head = None
    for val in reversed(values):
        head = ListNode(val, head)
    return head


def list_to_array(head: ListNode | None) -> list[int]:
    result = []
    while head:
        result.append(head.val)
        head = head.next
    return result


if __name__ == "__main__":
    head = build_list([1, 2, 3, 4, 5])
    reversed_head = reverse_list(head)
    print(list_to_array(reversed_head))  # [5, 4, 3, 2, 1]
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 4: Merge Two Sorted Lists
**Statement:** Merge two sorted linked lists into one sorted linked list and return its head.

**Example:**
```
Input: list1 = 1 -> 2 -> 4, list2 = 1 -> 3 -> 4
Output: 1 -> 1 -> 2 -> 3 -> 4 -> 4
```

**Approach:** Use a dummy "placeholder" head node to simplify edge cases. Walk both lists simultaneously with two pointers, always attaching the smaller current node to the result, and advancing that list's pointer. When one list runs out, attach the rest of the other list directly.

```python
class ListNode:
    def __init__(self, val: int = 0, next: "ListNode | None" = None):
        self.val = val
        self.next = next


def merge_two_lists(list1: ListNode | None, list2: ListNode | None) -> ListNode | None:
    dummy = ListNode()
    tail = dummy

    while list1 and list2:
        if list1.val <= list2.val:
            tail.next = list1
            list1 = list1.next
        else:
            tail.next = list2
            list2 = list2.next
        tail = tail.next

    tail.next = list1 if list1 else list2
    return dummy.next


def build_list(values: list[int]) -> ListNode | None:
    head = None
    for val in reversed(values):
        head = ListNode(val, head)
    return head


def list_to_array(head: ListNode | None) -> list[int]:
    result = []
    while head:
        result.append(head.val)
        head = head.next
    return result


if __name__ == "__main__":
    l1 = build_list([1, 2, 4])
    l2 = build_list([1, 3, 4])
    merged = merge_two_lists(l1, l2)
    print(list_to_array(merged))  # [1, 1, 2, 3, 4, 4]
```

**Complexity:** Time O(n + m), Space O(1) extra (ignoring the output nodes which are reused from inputs).

---

### Problem 5: Linked List Cycle Detection
**Statement:** Given the head of a linked list, determine if it has a cycle (some node's `next` eventually points back to an earlier node).

**Example:**
```
Input: 3 -> 2 -> 0 -> -4 -> (back to 2)
Output: True
```

**Approach:** Use **Floyd's Tortoise and Hare** algorithm: a slow pointer moves one step at a time, a fast pointer moves two steps at a time. If there's a cycle, the fast pointer will eventually "lap" the slow pointer and they'll meet. If there's no cycle, the fast pointer reaches `None` first.

```python
class ListNode:
    def __init__(self, val: int = 0):
        self.val = val
        self.next: "ListNode | None" = None


def has_cycle(head: ListNode | None) -> bool:
    slow = head
    fast = head

    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
        if slow is fast:
            return True

    return False


if __name__ == "__main__":
    # Build a cyclic list: 3 -> 2 -> 0 -> -4 -> back to 2
    n1 = ListNode(3)
    n2 = ListNode(2)
    n3 = ListNode(0)
    n4 = ListNode(-4)
    n1.next, n2.next, n3.next, n4.next = n2, n3, n4, n2  # cycle back to n2
    print(has_cycle(n1))  # True

    # Non-cyclic list
    a = ListNode(1)
    b = ListNode(2)
    a.next = b
    print(has_cycle(a))  # False
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 6: Daily Temperatures (Monotonic Stack)
**Statement:** Given an array of daily temperatures, return an array where `answer[i]` is the number of days you'd have to wait after day `i` to get a warmer temperature. If no future day is warmer, use `0`.

**Example:**
```
Input: temperatures = [73, 74, 75, 71, 69, 72, 76, 73]
Output: [1, 1, 4, 2, 1, 1, 0, 0]
```

**Approach:** Use a stack that holds indices of days we're still "waiting" for a warmer temperature. Scan left to right: while the stack's top index has a temperature lower than the current day, pop it and record the distance (current index - popped index) as its answer. Then push the current index. This is a **monotonic decreasing stack** — the temperatures corresponding to indices in the stack are always decreasing from bottom to top.

```python
def daily_temperatures(temperatures: list[int]) -> list[int]:
    answer = [0] * len(temperatures)
    stack: list[int] = []  # holds indices, waiting for a warmer day

    for i, temp in enumerate(temperatures):
        while stack and temperatures[stack[-1]] < temp:
            prev_index = stack.pop()
            answer[prev_index] = i - prev_index
        stack.append(i)

    return answer


if __name__ == "__main__":
    print(daily_temperatures([73, 74, 75, 71, 69, 72, 76, 73]))
    # [1, 1, 4, 2, 1, 1, 0, 0]
    print(daily_temperatures([30, 40, 50, 60]))
    # [1, 1, 1, 0]
```

**Complexity:** Time O(n) — every index is pushed once and popped at most once. Space O(n).

---

### Problem 7: LRU Cache
**Statement:** Design a Least Recently Used (LRU) cache with `get(key)` and `put(key, value)`, both running in O(1) average time. When capacity is exceeded, evict the least recently used item.

**Example:**
```
cache = LRUCache(2)
cache.put(1, 1)
cache.put(2, 2)
cache.get(1)       # 1 (and marks 1 as recently used)
cache.put(3, 3)    # evicts key 2 (least recently used)
cache.get(2)       # -1 (not found)
```

**Approach:** Combine a hash map (for O(1) key lookup) with a **doubly linked list** (to track usage order — most recently used at one end, least recently used at the other). On `get`, move the accessed node to the "most recently used" end. On `put`, if over capacity, remove the node at the "least recently used" end. Python's `collections.OrderedDict` gives us this behavior directly and simply.

```python
from collections import OrderedDict

class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache: OrderedDict[int, int] = OrderedDict()

    def get(self, key: int) -> int:
        if key not in self.cache:
            return -1
        self.cache.move_to_end(key)  # mark as most recently used
        return self.cache[key]

    def put(self, key: int, value: int) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)  # evict least recently used


if __name__ == "__main__":
    cache = LRUCache(2)
    cache.put(1, 1)
    cache.put(2, 2)
    print(cache.get(1))  # 1
    cache.put(3, 3)       # evicts key 2
    print(cache.get(2))  # -1
    cache.put(4, 4)       # evicts key 1
    print(cache.get(1))  # -1
    print(cache.get(3))  # 3
    print(cache.get(4))  # 4
```

**Complexity:** Time O(1) average for both `get` and `put`, Space O(capacity).

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Valid Parentheses | O(n) | O(n) |
| Implement Queue Using Stacks | O(1) amortized | O(n) |
| Reverse Linked List | O(n) | O(1) |
| Merge Two Sorted Lists | O(n + m) | O(1) |
| Linked List Cycle Detection | O(n) | O(1) |
| Daily Temperatures | O(n) | O(n) |
| LRU Cache | O(1) average | O(capacity) |

---

## 6. Interview Tips

- **For linked lists, always ask about edge cases first:** empty list, single node, and (for cycle problems) whether a cycle is even possible. Drawing boxes-and-arrows on paper/whiteboard before coding avoids pointer bugs.
- **Dummy nodes are your friend.** In merge/insert/delete problems, a dummy head node removes a ton of "is this the first node?" special-casing. Mention this trick explicitly — it signals experience.
- **Name the pointer technique.** Saying "I'll use Floyd's cycle detection, also called the tortoise and hare" during a cycle problem shows you recognize the pattern by name, which builds interviewer confidence quickly.
- **For stack problems, describe the invariant of the stack.** For "Daily Temperatures," say explicitly: "My stack will always hold indices with strictly decreasing temperatures, so I can pop whenever I find something taller." Naming the invariant turns a tricky algorithm into an obvious one.
- **For LRU Cache, mention the two building blocks by name:** "a hash map for O(1) lookup, plus a doubly linked list (or Python's OrderedDict) to track recency order in O(1)." Even if you use `OrderedDict`, be ready to explain how you'd build the doubly linked list + hash map version manually, since some interviewers ask for that.
