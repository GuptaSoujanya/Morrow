# Chapter 6: Heaps & Priority Queues

## 1. Concept

A **heap** is a tree-shaped data structure (usually stored in a plain array) that keeps the smallest (min-heap) or largest (max-heap) element always available at the root in O(1) time, with O(log n) insert and remove. A **priority queue** is the abstract concept — "give me the most important item next" — and a heap is the standard way to implement it efficiently.

Python's `heapq` module implements a **min-heap** only. To simulate a max-heap, negate values before pushing and negate again after popping.

```
Min-Heap (array stored, but think of it as a tree):

           1
         /   \
        3     5
       / \   /
      9   6 8

Array form: [1, 3, 5, 9, 6, 8]
Rule: parent <= both children, for every node.

Index math (0-indexed array):
  parent(i) = (i - 1) // 2
  left(i)   = 2*i + 1
  right(i)  = 2*i + 2
```

Why a heap instead of sorting? Sorting the whole collection is O(n log n), but if you only ever need the current min/max repeatedly, a heap keeps that operation at O(log n) per insert/remove — much cheaper when the data arrives over time or you don't need full order.

## 2. When to Use This Pattern

- "Find the k-th largest/smallest" or "top-k" something → heap of size k.
- "Merge k sorted lists/arrays" → min-heap holding one element from each list.
- "Process tasks by priority" or "always pick the cheapest/most urgent next" → priority queue.
- "Median of a running stream" → two heaps (one max-heap for the lower half, one min-heap for the upper half).
- Dijkstra's shortest path, Prim's MST → these use a min-heap internally (see Chapter 7).

## 3. Template / Skeleton Code

```python
import heapq

def k_largest_template(nums: list[int], k: int) -> list[int]:
    """Maintain a min-heap of size k; its root is the k-th largest seen so far."""
    min_heap: list[int] = []
    for num in nums:
        heapq.heappush(min_heap, num)
        if len(min_heap) > k:
            heapq.heappop(min_heap)  # remove the smallest, keep the k largest
    return min_heap


def max_heap_template(nums: list[int]) -> list[int]:
    """Simulate a max-heap by negating values."""
    max_heap = [-num for num in nums]
    heapq.heapify(max_heap)
    result = []
    while max_heap:
        result.append(-heapq.heappop(max_heap))
    return result
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Kth Largest Element in an Array
**Statement:** Given an integer array and an integer `k`, return the k-th largest element (not the k-th distinct element).

**Example:**
```
Input: nums = [3, 2, 1, 5, 6, 4], k = 2
Output: 5
```

**Approach:** Keep a min-heap of size `k`. Push every number; whenever the heap grows past size `k`, pop the smallest. After processing everything, the heap holds exactly the `k` largest numbers, and its root (smallest of those) is the k-th largest overall.

```python
import heapq

def find_kth_largest(nums: list[int], k: int) -> int:
    min_heap: list[int] = []
    for num in nums:
        heapq.heappush(min_heap, num)
        if len(min_heap) > k:
            heapq.heappop(min_heap)
    return min_heap[0]


if __name__ == "__main__":
    print(find_kth_largest([3, 2, 1, 5, 6, 4], 2))  # 5
    print(find_kth_largest([3, 2, 3, 1, 2, 4, 5, 5, 6], 4))  # 4
```

**Complexity:** Time O(n log k), Space O(k).

---

### Problem 2: Last Stone Weight
**Statement:** You have stones with given weights. Repeatedly pick the two heaviest stones, smash them together: if weights `x <= y`, the stone of weight `x` is destroyed and the stone of weight `y` becomes `y - x`. If `x == y`, both are destroyed. Return the weight of the last remaining stone, or 0 if none remain.

**Example:**
```
Input: stones = [2, 7, 4, 1, 8, 1]
Output: 1
```

**Approach:** We always need the two *largest* stones, repeatedly — a perfect use of a max-heap. Simulate it by negating values for Python's min-heap.

```python
import heapq

def last_stone_weight(stones: list[int]) -> int:
    max_heap = [-s for s in stones]
    heapq.heapify(max_heap)

    while len(max_heap) > 1:
        y = -heapq.heappop(max_heap)  # heaviest
        x = -heapq.heappop(max_heap)  # second heaviest
        if y != x:
            heapq.heappush(max_heap, -(y - x))

    return -max_heap[0] if max_heap else 0


if __name__ == "__main__":
    print(last_stone_weight([2, 7, 4, 1, 8, 1]))  # 1
    print(last_stone_weight([1]))                   # 1
    print(last_stone_weight([2, 2]))                # 0
```

**Complexity:** Time O(n log n), Space O(n).

---

### Problem 3: K Closest Points to Origin
**Statement:** Given an array of points `[x, y]` and an integer `k`, return the `k` closest points to the origin `(0, 0)`.

**Example:**
```
Input: points = [[1,3],[-2,2]], k = 1
Output: [[-2,2]]
```

**Approach:** Keep a max-heap of size `k` based on squared distance (no need for a real square root — it doesn't change ordering and avoids float issues). Push each point's `(-distance, point)`; if the heap grows past `k`, pop the farthest. At the end, the heap holds the `k` closest points.

```python
import heapq

def k_closest(points: list[list[int]], k: int) -> list[list[int]]:
    max_heap: list[tuple[int, list[int]]] = []

    for x, y in points:
        dist_sq = x * x + y * y
        heapq.heappush(max_heap, (-dist_sq, [x, y]))
        if len(max_heap) > k:
            heapq.heappop(max_heap)

    return [point for _, point in max_heap]


if __name__ == "__main__":
    print(k_closest([[1, 3], [-2, 2]], 1))              # [[-2, 2]]
    print(sorted(k_closest([[3, 3], [5, -1], [-2, 4]], 2)))  # [[-2, 4], [3, 3]]
```

**Complexity:** Time O(n log k), Space O(k).

---

### Problem 4: Task Scheduler
**Statement:** Given a list of tasks (characters) and a cooldown `n` (same task must wait `n` intervals before it can run again), return the minimum number of time units needed to finish all tasks (idle slots count too).

**Example:**
```
Input: tasks = ["A","A","A","B","B","B"], n = 2
Output: 8   # A B idle A B idle A B
```

**Approach:** Greedily always run the most frequent remaining task next (a max-heap by frequency), since that task has the biggest "cooldown debt" to pay off. After running a task, put it in a cooldown queue with the time it becomes available again. Check that queue each tick to see if a task has finished cooling down and can go back into the heap.

```python
import heapq
from collections import Counter, deque

def least_interval(tasks: list[str], n: int) -> int:
    counts = Counter(tasks)
    max_heap = [-count for count in counts.values()]
    heapq.heapify(max_heap)

    time = 0
    cooldown: deque[tuple[int, int]] = deque()  # (available_count, available_time)

    while max_heap or cooldown:
        time += 1
        if max_heap:
            count = heapq.heappop(max_heap) + 1  # one less negative = one less remaining
            if count != 0:
                cooldown.append((count, time + n))

        if cooldown and cooldown[0][1] == time:
            ready_count, _ = cooldown.popleft()
            heapq.heappush(max_heap, ready_count)

    return time


if __name__ == "__main__":
    print(least_interval(["A", "A", "A", "B", "B", "B"], 2))  # 8
    print(least_interval(["A", "A", "A", "B", "B", "B"], 0))  # 6
    print(least_interval(["A", "A", "A", "A", "A", "A", "B", "C", "D", "E", "F", "G"], 2))  # 16
```

**Complexity:** Time O(total_tasks), since the heap holds at most 26 distinct task types regardless of input size. Space O(26) = O(1).

---

### Problem 5: Find Median from Data Stream
**Statement:** Design a data structure that supports adding numbers one at a time (`add_num`) and finding the median of all numbers added so far (`find_median`), both efficiently.

**Example:**
```
add_num(1)
add_num(2)
find_median()  # 1.5
add_num(3)
find_median()  # 2.0
```

**Approach:** Maintain two heaps: a max-heap for the smaller half of numbers, and a min-heap for the larger half. Keep them balanced in size (differing by at most 1). The median is either the top of the larger heap (odd total count) or the average of both tops (even total count).

```python
import heapq

class MedianFinder:
    def __init__(self):
        self.small: list[int] = []  # max-heap (negated), holds the smaller half
        self.large: list[int] = []  # min-heap, holds the larger half

    def add_num(self, num: int) -> None:
        heapq.heappush(self.small, -num)

        # Ensure every element in small <= every element in large
        if self.small and self.large and -self.small[0] > self.large[0]:
            val = -heapq.heappop(self.small)
            heapq.heappush(self.large, val)

        # Rebalance sizes so they differ by at most 1
        if len(self.small) > len(self.large) + 1:
            val = -heapq.heappop(self.small)
            heapq.heappush(self.large, val)
        elif len(self.large) > len(self.small) + 1:
            val = heapq.heappop(self.large)
            heapq.heappush(self.small, -val)

    def find_median(self) -> float:
        if len(self.small) > len(self.large):
            return -self.small[0]
        if len(self.large) > len(self.small):
            return self.large[0]
        return (-self.small[0] + self.large[0]) / 2.0


if __name__ == "__main__":
    mf = MedianFinder()
    mf.add_num(1)
    mf.add_num(2)
    print(mf.find_median())  # 1.5
    mf.add_num(3)
    print(mf.find_median())  # 2.0
```

**Complexity:** Time O(log n) per `add_num`, O(1) per `find_median`. Space O(n).

---

### Problem 6: Merge K Sorted Lists
**Statement:** Given an array of `k` linked lists, each sorted ascending, merge them into one sorted linked list.

**Example:**
```
Input: lists = [[1,4,5],[1,3,4],[2,6]]
Output: [1,1,2,3,4,4,5,6]
```

**Approach:** A min-heap holds at most one "current" node from each list at a time — the smallest among them is always at the top. Pop the smallest, attach it to the result, and if that list has a next node, push it into the heap. Repeat until the heap is empty.

```python
import heapq

class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next


def merge_k_lists(lists: list[ListNode | None]) -> ListNode | None:
    heap: list[tuple[int, int, ListNode]] = []
    for i, node in enumerate(lists):
        if node:
            # include index i as a tiebreaker since ListNode isn't comparable
            heapq.heappush(heap, (node.val, i, node))

    dummy = ListNode()
    tail = dummy

    while heap:
        val, i, node = heapq.heappop(heap)
        tail.next = node
        tail = tail.next
        if node.next:
            heapq.heappush(heap, (node.next.val, i, node.next))

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
    lists = [build_list([1, 4, 5]), build_list([1, 3, 4]), build_list([2, 6])]
    merged = merge_k_lists(lists)
    print(list_to_array(merged))  # [1, 1, 2, 3, 4, 4, 5, 6]
```

**Complexity:** Time O(N log k) where N is the total number of nodes and k is the number of lists. Space O(k) for the heap.

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Kth Largest Element in an Array | O(n log k) | O(k) |
| Last Stone Weight | O(n log n) | O(n) |
| K Closest Points to Origin | O(n log k) | O(k) |
| Task Scheduler | O(n) | O(1) |
| Find Median from Data Stream | O(log n) add, O(1) median | O(n) |
| Merge K Sorted Lists | O(N log k) | O(k) |

---

## 6. Interview Tips

- **Say min-heap vs max-heap explicitly, and why.** For "kth largest," explain: "I'll keep a min-heap of size k — counterintuitively a *min*-heap, because I want to be able to cheaply evict the smallest of my current top-k candidates whenever a bigger one arrives."
- **Mention that Python's `heapq` is min-heap only.** If you need max-heap behavior, say you'll negate values — this is a small detail, but forgetting to mention it and then silently negating in code can confuse interviewers watching you type.
- **For "two-heap" problems like running median, draw the split explicitly.** Describe it as "a max-heap holding the smaller half, a min-heap holding the larger half, kept balanced within 1 in size" — this mental model generalizes to several other streaming problems.
- **Compare to sorting out loud.** Say: "Sorting everything would be O(n log n) one-time, but a heap lets me do this incrementally in O(log n) per operation as new data arrives" — this shows you understand *why* a heap is chosen, not just how to use `heapq`.
- **For Task Scheduler, name the greedy insight.** Say: "I always want to schedule the task with the most remaining occurrences first, because it has the least slack before hitting the cooldown constraint again" — this one sentence usually convinces an interviewer you understand the greedy heap choice, not just memorized code.
