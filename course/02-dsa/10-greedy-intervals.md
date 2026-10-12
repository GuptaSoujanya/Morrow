# Chapter 10: Greedy & Intervals

## 1. Concept

A **greedy algorithm** makes the locally best choice at every step, hoping (and, for the right problems, provably guaranteeing) that this leads to a globally optimal solution. Unlike DP, greedy never looks back or reconsiders — once a choice is made, it's final.

**Interval problems** are a common home for greedy thinking: given a list of `[start, end]` ranges, decide which to keep, merge, or remove, usually by sorting first.

```
Greedy choice-making (Activity Selection style):

Intervals (sorted by end time):
 [1,3]  [2,4]  [3,5]  [6,8]
  ---
       ---
            ---
                      ---

Greedy: always pick the interval that finishes earliest among
remaining valid candidates. This leaves the most room for future picks.

Picked: [1,3] -> skip [2,4] (overlaps) -> skip [3,5] (overlaps, starts at 3 < 3 end) -> pick [6,8]
Result: [1,3], [6,8]
```

The hard part of greedy isn't the code — it's **proving the greedy choice is safe**. In an interview, you're not expected to write a formal proof, but you should be able to explain intuitively why picking greedily at each step can't lead you astray.

## 2. When to Use This Pattern

- Problem involves intervals: "merge overlapping," "max non-overlapping," "minimum rooms/resources needed."
- "Maximize/minimize X" where a simple rule ("always pick the smallest/largest/earliest available option") feels intuitively correct and a counterexample is hard to construct.
- Sorting the input first makes the greedy choice obvious — this is a huge hint.
- DP would work but feels like overkill — simpler greedy reasoning suffices (contrast with Chapter 9).
- "Jump game" / reachability problems with a "furthest reach so far" tracking variable.

## 3. Template / Skeleton Code

```python
def greedy_interval_template(intervals: list[list[int]]) -> list[list[int]]:
    intervals.sort(key=lambda interval: interval[0])  # sort by start (often by end instead)
    result: list[list[int]] = []

    for interval in intervals:
        if result and interval[0] <= result[-1][1]:
            # overlaps with the last kept interval -> merge or skip
            result[-1][1] = max(result[-1][1], interval[1])
        else:
            result.append(interval)

    return result


def greedy_choice_template(items: list[int]) -> int:
    items.sort()  # or sort by a derived key
    count = 0
    for item in items:
        if is_valid_choice(item):
            count += 1
            # commit to this choice; never reconsider
    return count


def is_valid_choice(item: int) -> bool:
    return True  # placeholder
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Assign Cookies
**Statement:** Each child `i` has a greed factor `g[i]` (minimum cookie size that satisfies them). Each cookie `j` has a size `s[j]`. Each child can get at most one cookie. Maximize the number of satisfied children.

**Example:**
```
Input: g = [1, 2, 3], s = [1, 1]
Output: 1   # only one child (greed 1) can be satisfied with a size-1 cookie
```

**Approach:** Sort both arrays. Greedily try to satisfy the least-greedy child with the smallest cookie that's big enough. If the current smallest cookie is too small for the current least-greedy child, that cookie is useless for everyone pickier too — skip it. Using the smallest sufficient cookie for each child preserves larger cookies for greedier children later.

```python
def find_content_children(g: list[int], s: list[int]) -> int:
    g.sort()
    s.sort()

    child = 0
    cookie = 0

    while child < len(g) and cookie < len(s):
        if s[cookie] >= g[child]:
            child += 1  # this child is satisfied
        cookie += 1  # move to the next cookie either way

    return child


if __name__ == "__main__":
    print(find_content_children([1, 2, 3], [1, 1]))     # 1
    print(find_content_children([1, 2], [1, 2, 3]))      # 2
    print(find_content_children([], [1, 2]))               # 0
```

**Complexity:** Time O(n log n + m log m) for sorting, Space O(1) extra.

---

### Problem 2: Merge Intervals
**Statement:** Given an array of intervals, merge all overlapping intervals and return the merged, non-overlapping intervals.

**Example:**
```
Input: intervals = [[1,3],[2,6],[8,10],[15,18]]
Output: [[1,6],[8,10],[15,18]]
```

**Approach:** Sort intervals by start time. Walk through them, keeping a "current merged interval." If the next interval's start is ≤ the current merged interval's end, they overlap — extend the end if needed. Otherwise, the current merged interval is finished; save it and start a new one.

```python
def merge(intervals: list[list[int]]) -> list[list[int]]:
    if not intervals:
        return []

    intervals.sort(key=lambda interval: interval[0])
    merged = [intervals[0]]

    for start, end in intervals[1:]:
        last_end = merged[-1][1]
        if start <= last_end:
            merged[-1][1] = max(last_end, end)
        else:
            merged.append([start, end])

    return merged


if __name__ == "__main__":
    print(merge([[1, 3], [2, 6], [8, 10], [15, 18]]))  # [[1,6],[8,10],[15,18]]
    print(merge([[1, 4], [4, 5]]))                        # [[1,5]]
```

**Complexity:** Time O(n log n), Space O(n).

---

### Problem 3: Non-overlapping Intervals (Minimum Removals)
**Statement:** Given an array of intervals, find the minimum number of intervals you need to remove so that the rest don't overlap.

**Example:**
```
Input: intervals = [[1,2],[2,3],[3,4],[1,3]]
Output: 1   # remove [1,3]
```

**Approach:** This is the classic "Activity Selection" problem in disguise. Sort by **end time**. Greedily keep an interval if it starts at or after the end of the last kept interval (no overlap). Every interval we can't keep must be removed. Sorting by end time (not start time) is the key insight — it always leaves the maximum room for future intervals.

```python
def erase_overlap_intervals(intervals: list[list[int]]) -> int:
    if not intervals:
        return 0

    intervals.sort(key=lambda interval: interval[1])  # sort by end time
    kept_end = intervals[0][1]
    kept_count = 1

    for start, end in intervals[1:]:
        if start >= kept_end:
            kept_count += 1
            kept_end = end

    return len(intervals) - kept_count


if __name__ == "__main__":
    print(erase_overlap_intervals([[1, 2], [2, 3], [3, 4], [1, 3]]))  # 1
    print(erase_overlap_intervals([[1, 2], [1, 2], [1, 2]]))            # 2
    print(erase_overlap_intervals([[1, 2], [2, 3]]))                     # 0
```

**Complexity:** Time O(n log n), Space O(1) extra.

---

### Problem 4: Meeting Rooms II (Minimum Rooms Needed)
**Statement:** Given meeting time intervals, find the minimum number of conference rooms required so no two meetings overlap in the same room.

**Example:**
```
Input: intervals = [[0,30],[5,10],[15,20]]
Output: 2
```

**Approach:** Separate all start times and all end times into two sorted lists. Walk through start times in order; for each new meeting starting, check if the earliest-ending currently-occupied room has already freed up (its end time ≤ this start time) — if so, reuse that room (advance the end-pointer); otherwise, we need a new room. Track the maximum rooms in use at any time.

```python
def min_meeting_rooms(intervals: list[list[int]]) -> int:
    if not intervals:
        return 0

    starts = sorted(interval[0] for interval in intervals)
    ends = sorted(interval[1] for interval in intervals)

    rooms_needed = 0
    max_rooms = 0
    end_pointer = 0

    for start in starts:
        while end_pointer < len(ends) and ends[end_pointer] <= start:
            rooms_needed -= 1  # a room freed up before this meeting starts
            end_pointer += 1
        rooms_needed += 1  # this meeting needs a room
        max_rooms = max(max_rooms, rooms_needed)

    return max_rooms


if __name__ == "__main__":
    print(min_meeting_rooms([[0, 30], [5, 10], [15, 20]]))  # 2
    print(min_meeting_rooms([[7, 10], [2, 4]]))                # 1
    print(min_meeting_rooms([]))                                 # 0
```

**Complexity:** Time O(n log n), Space O(n).

---

### Problem 5: Jump Game
**Statement:** Given an array where `nums[i]` is the maximum jump length from index `i`, starting at index 0, determine if you can reach the last index.

**Example:**
```
Input: nums = [2, 3, 1, 1, 4]
Output: True

Input: nums = [3, 2, 1, 0, 4]
Output: False
```

**Approach:** Track the furthest index reachable so far. Walk through the array left to right; if the current index is beyond the furthest reachable point, we're stuck — return `False`. Otherwise, greedily update the furthest reachable point using `i + nums[i]`. This greedy update is safe because we never need to "remember" a specific earlier jump — only the best (furthest) reach matters.

```python
def can_jump(nums: list[int]) -> bool:
    furthest = 0

    for i, num in enumerate(nums):
        if i > furthest:
            return False  # stuck: can't reach index i at all
        furthest = max(furthest, i + num)

    return True


if __name__ == "__main__":
    print(can_jump([2, 3, 1, 1, 4]))  # True
    print(can_jump([3, 2, 1, 0, 4]))  # False
    print(can_jump([0]))               # True (already at the last index)
```

**Complexity:** Time O(n), Space O(1).

---

### Problem 6: Gas Station
**Statement:** There are `n` gas stations in a circle. `gas[i]` is the gas available at station `i`; `cost[i]` is the gas needed to travel from station `i` to station `i+1`. Starting with an empty tank, find the starting station index from which you can complete the full circuit, or return `-1` if impossible (guaranteed at most one valid answer exists).

**Example:**
```
Input: gas = [1,2,3,4,5], cost = [3,4,5,1,2]
Output: 3
```

**Approach:** Two key greedy insights: (1) if total gas ≥ total cost, a valid starting point must exist; (2) if starting from station `s` and running out of gas at station `i`, then no station between `s` and `i` (inclusive) can be a valid start either, because they'd all arrive at `i` with even less fuel than starting from `s` did. So whenever the running tank goes negative, reset the candidate start to the very next station and reset the tank to 0.

```python
def can_complete_circuit(gas: list[int], cost: list[int]) -> int:
    if sum(gas) < sum(cost):
        return -1

    tank = 0
    start = 0

    for i in range(len(gas)):
        tank += gas[i] - cost[i]
        if tank < 0:
            start = i + 1  # this and all stations up to i are invalid starts
            tank = 0

    return start


if __name__ == "__main__":
    print(can_complete_circuit([1, 2, 3, 4, 5], [3, 4, 5, 1, 2]))  # 3
    print(can_complete_circuit([2, 3, 4], [3, 4, 3]))                 # -1
```

**Complexity:** Time O(n), Space O(1).

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Assign Cookies | O(n log n + m log m) | O(1) |
| Merge Intervals | O(n log n) | O(n) |
| Non-overlapping Intervals | O(n log n) | O(1) |
| Meeting Rooms II | O(n log n) | O(n) |
| Jump Game | O(n) | O(1) |
| Gas Station | O(n) | O(1) |

---

## 6. Interview Tips

- **Say the sort key out loud, and justify it.** For interval problems, explicitly state: "I'll sort by end time, not start time, because that leaves the most room for future choices" (Non-overlapping Intervals) vs. "I'll sort by start time here because I need to detect overlaps as I merge left to right" (Merge Intervals). Picking the wrong sort key is the most common bug in this chapter.
- **Try to sketch a quick counterexample yourself before committing to a greedy approach.** Interviewers respect candidates who say: "Let me check if always picking the smallest/earliest option could ever backfire..." even if you conclude it doesn't. This shows rigor, not just pattern memorization.
- **Contrast greedy with DP explicitly when relevant.** If you're unsure whether a problem needs greedy or DP, say: "A greedy choice works here because once I commit to this pick, no future information could make me want to undo it — unlike DP, where an early choice might look good locally but turn out suboptimal globally."
- **For "two pointers over sorted start/end arrays" (Meeting Rooms II), describe it as a timeline sweep.** Say: "I'm sweeping through time, counting how many meetings are active at once — this is sometimes called a sweep line algorithm."
- **For Gas Station, explain the reset logic carefully.** This is the trickiest proof in the chapter. Say explicitly: "If I run out of gas at station i while starting from s, every station between s and i would run out even earlier, so none of them can be valid starts either — I can safely jump my candidate start all the way to i+1."
