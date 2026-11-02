"""Interview-depth explanations for the 22 stable daily DSA topics.

The walkthroughs are authored examples aligned to the bundled problem mapping.
They describe expected reasoning, not claims that a learner executed code.
There are no network calls or progress writes in this content module.
"""
from __future__ import annotations

from copy import deepcopy
from textwrap import dedent


SOURCES = [
    {'title': 'MIT 6.006: hashing', 'url': 'https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_lec08/'},
    {'title': 'MIT 6.006: breadth-first search', 'url': 'https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_lec13/'},
    {'title': 'MIT 6.006: DFS and topological sorting', 'url': 'https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_lec14/'},
    {'title': 'MIT 6.006: Dijkstra', 'url': 'https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_lec16/'},
    {'title': 'MIT 6.006: dynamic programming', 'url': 'https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_lec19/'},
    {'title': 'MIT 6.006: edit distance and knapsack', 'url': 'https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_lec21/'},
    {'title': 'Python: heap operations', 'url': 'https://docs.python.org/3/library/heapq.html'},
    {'title': 'Python: binary-search boundaries', 'url': 'https://docs.python.org/3/library/bisect.html'},
    {'title': 'Jeff Erickson: backtracking', 'url': 'https://jeffe.cs.illinois.edu/teaching/algorithms/book/02-backtracking.pdf'},
    {'title': 'Jeff Erickson: greedy algorithms', 'url': 'https://jeffe.cs.illinois.edu/teaching/algorithms/book/04-greedy.pdf'},
    {'title': 'kdn251/interviews: data structures and algorithms overview (MIT)', 'url': 'https://github.com/kdn251/interviews#data-structures'},
]


def _topic(concept, walkthrough, interview):
    return {key: dedent(value).strip() for key, value in
            (('concept', concept), ('walkthrough', walkthrough), ('interview', interview))}


_TOPICS = {
    'hashing': _topic(
        """
        ## Recognise the pattern

        Use a set when the question asks whether a value appeared before. Use a map when you need a count or an earlier index. In **Contains Duplicate**, the important information is membership, not ordering. Ask whether the input can be changed and whether memory is limited before choosing an approach.

        ## Compare approaches and prove the choice

        Checking every pair takes O(n²) time and O(1) extra space. Sorting and checking neighbours takes O(n log n) time; sorting may change the input and its memory cost depends on the implementation. A hash set gives expected O(n) time with O(n) extra space. Hash operations are expected constant time under suitable hashing, not an unconditional worst-case promise.

        The **invariant**, meaning the fact that stays true, is: before reading position i, the set contains exactly the distinct values in earlier positions. If the next value is present, an earlier equal value exists. Otherwise, adding it preserves the invariant. Reaching the end without a match proves that no pair repeats.

        Check an empty list, one item, equal neighbours, a repeat far apart, zero, and negative numbers. A hash collision is not itself a duplicate: the data structure must compare keys for equality.
        """,
        """
        ## Walk through Contains Duplicate

        Input: `[1, 2, 3, 1]`. Check membership **before** adding the current item. Adding first would make every value appear to repeat itself.

        | Position | Value | Set before check | Decision |
        | --- | --- | --- | --- |
        | 0 | 1 | empty | Add 1 |
        | 1 | 2 | {1} | Add 2 |
        | 2 | 3 | {1, 2} | Add 3 |
        | 3 | 1 | {1, 2, 3} | Return true |

        ```mermaid
        flowchart TD
          A[Read next value] --> B{Already in seen set?}
          B -->|Yes| C[Return duplicate found]
          B -->|No| D[Add value to seen]
          D --> E{More values?}
          E -->|Yes| A
          E -->|No| F[Return no duplicate]
        ```

        The early return is valid because the question needs one duplicate, not the full list of repeated values. If the requested output changes, the stored state may need to change too.
        """,
        """
        ## Interview follow-up

        In **Two Sum**, why check for `target - value` before storing the current index? Explain `[3, 3]` with target 6. Then explain why **Valid Anagram** needs counts rather than only a set.

        ### Check your answer

        At index 0, complement 3 is absent, so save `3: 0`. At index 1, complement 3 points to index 0, giving two different positions. Inserting first could pair a value with its own index. This is expected O(n) time and O(n) space; clarify whether any valid pair is acceptable.

        Sets cannot distinguish `aab` from `abb`: both contain a and b. Compare frequency maps, or update counts and ensure all balances return to zero. With an agreed fixed alphabet, a fixed-size count array uses bounded space. Practise explaining the invariant before writing the loop, then test a single 3 to ensure it cannot pair with itself.
        """),
    'array-patterns': _topic(
        """
        ## Recognise the pattern

        **Group Anagrams** asks you to group items by meaning rather than exact spelling. Build a canonical key: a representation that is identical precisely when two words belong together. The difficult design choice is the key, not the dictionary loop.

        ## Compare approaches and prove the choice

        Comparing every word with existing group members can require quadratically many comparisons. Sorting each word gives a simple key such as `aet`. For n words of maximum length k, this takes O(n k log k) time, with output and stored keys using O(nk) space in the worst case.

        If input is restricted to lowercase English letters, a 26-count tuple gives O(nk) expected time, plus the fixed work of constructing each tuple. Do not claim the same fixed space for an unrestricted alphabet. Unicode normalization and case sensitivity are product rules that must be agreed first.

        The invariant is: every processed word is in the group matching its exact character counts. Equal counts are necessary and sufficient for a rearrangement. A plain sum of character codes is unsafe because different character combinations can share that sum.

        Test empty words, repeated words, different lengths, and a case such as `ab` versus `ba`. The output group order is unspecified; tests should compare groups accordingly.
        """,
        """
        ## Walk through Group Anagrams

        Use sorted-character keys for `eat, tea, tan, ate, nat, bat`. Each row changes only one group; earlier groups stay valid.

        | Word | Key | Group after insertion |
        | --- | --- | --- |
        | eat | aet | eat |
        | tea | aet | eat, tea |
        | tan | ant | tan |
        | ate | aet | eat, tea, ate |
        | nat | ant | tan, nat |
        | bat | abt | bat |

        ```mermaid
        flowchart TD
          A[Read word] --> B[Build character signature]
          B --> C{Signature has a group?}
          C -->|No| D[Create empty group]
          C -->|Yes| E[Append original word]
          D --> E
          E --> F[Continue or return all groups]
        ```

        Store the original word in the result. The key is only for grouping; returning sorted keys would lose the requested spellings and repeated entries.
        """,
        """
        ## Interview follow-up

        Your practices are **Top K Frequent Elements** and **Product of Array Except Self**. Which stored summary makes each efficient? Work through product-except-self for `[1, 2, 0, 4]` without division.

        ### Check your answer

        Top K first counts occurrences, then selects the largest frequencies using a size-k heap or frequency buckets. Counting alone does not produce the requested ranking. A heap gives O(n + u log k) expected time for u distinct values, with count storage O(u).

        For products, save each position's product strictly to its left: `[1, 1, 2, 0]`. Walk backward with a right-side product and multiply it into each result. The answer is `[0, 0, 8, 0]`. This takes O(n) time and O(1) extra working space beyond the output. Two zeros make every answer zero. Explain the left/right invariant instead of adding special-case division logic.
        """),
    'two-pointers': _topic(
        """
        ## Recognise the pattern

        Two pointers help when ordered positions let you discard work safely. In **Valid Palindrome**, the first and last meaningful characters must match. In sorted pair-sum problems, increasing the left value or decreasing the right value changes the sum predictably. These are different proofs using the same pointer vocabulary.

        ## Compare approaches and prove the choice

        A clear baseline filters and lowercases the whole string, then compares it with its reversal: O(n) time and O(n) extra space. Two indices skip non-alphanumeric characters in place and compare the ends. Under the stated character model, this is O(n) time and O(1) extra space; every index moves inward at most n times.

        The invariant is that all meaningful characters outside the current interval have matched their opposite partners. A mismatch proves failure immediately. When the pointers meet or cross, no unchecked pair remains. Guard both skip loops with the boundary condition so punctuation-only input does not access past the string.

        Clarify ASCII versus broader Unicode rules. Per-character lowercase comparisons are not automatically a complete language-aware normalization strategy. For this interview walkthrough, use ASCII letters and digits.

        Test empty input, one character, only punctuation, mixed case, and a mismatch near the middle. Explain why skipping punctuation does not skip a meaningful comparison.
        """,
        """
        ## Walk through Valid Palindrome

        Input: `A, b!a`. After ignoring punctuation and spaces, its meaningful sequence is `aba`.

        | Left position | Right position | Work | Result |
        | --- | --- | --- | --- |
        | 0: A | 5: a | Compare lowercase letters | Match |
        | 1: comma | 4: ! | Skip punctuation on both sides | Move inward |
        | 2: space | 3: b | Skip space | Both reach b |
        | 3: b | 3: b | No pair remains | Return true |

        ```mermaid
        flowchart TD
          A[Skip non-alphanumeric ends] --> B{Left below right?}
          B -->|No| C[Return true]
          B -->|Yes| D{Lowercase values equal?}
          D -->|No| E[Return false]
          D -->|Yes| F[Move both inward]
          F --> A
        ```

        Notice that punctuation skipping and matching are separate operations. A pointer must never move outward, or the linear-work argument fails.
        """,
        """
        ## Interview follow-up

        In **Two Sum II**, why is moving left safe when the current sum is too small? How does **3Sum** reuse this reasoning without returning duplicate triples?

        ### Check your answer

        In a sorted array, pairing the current left value with any position at or below the current right gives a sum no larger than the current sum. Therefore that left value cannot reach the target inside the remaining interval; discard it. The opposite argument applies when the sum is too large.

        For 3Sum, sort, fix one value, and search the suffix for its negation using two pointers. Skip repeated fixed values and skip repeated pair values after a match. Sorting plus all suffix scans takes O(n²) time overall. State sorting memory separately from the result, which can itself be large. Try `[-1, -1, 0, 1, 2]` and explain why `[-1, 0, 1]` appears once.
        """),
    'sliding-window': _topic(
        """
        ## Recognise the pattern

        A window tracks a contiguous part of input while its boundaries move forward. The mapped example, **Best Time to Buy and Sell Stock**, is best understood as a running minimum: each selling day needs the cheapest earlier buying day. It introduces one-way scanning, but it does not require a general frequency-window implementation.

        ## Compare approaches and prove the choice

        Trying every buy/sell pair takes O(n²) time and O(1) space. Scan once while keeping the lowest earlier price and best legal profit. This takes O(n) time and O(1) extra space. Before processing a selling day, the minimum describes earlier days and the best value describes earlier completed pairs.

        Compute today's possible profit before adding today's price to the earlier minimum. This makes the later-day requirement explicit. Start the best profit at zero because choosing no transaction is allowed. A lower current price becomes useful for future days, even if selling today is unattractive.

        Empty or one-day input cannot produce a transaction. Test decreasing prices, equal prices, and a late new minimum. The method assumes one buy followed by one sell; unlimited transactions require different reasoning.

        General variable windows need a condition that tells you when removing leftmost items restores validity. Do not apply a positive-number sum window unchanged when negative numbers break that condition.
        """,
        """
        ## Walk through Best Time to Buy and Sell Stock

        Input: `[7, 1, 5, 3, 6, 4]`. Initialise the minimum to the first price and the best profit to zero.

        | Selling price | Earlier minimum | Candidate profit | Best so far |
        | --- | --- | --- | --- |
        | 1 | 7 | -6 | 0 |
        | 5 | 1 | 4 | 4 |
        | 3 | 1 | 2 | 4 |
        | 6 | 1 | 5 | 5 |
        | 4 | 1 | 3 | 5 |

        ```mermaid
        flowchart TD
          A[Take next selling price] --> B[Compare price minus earlier minimum]
          B --> C[Update best legal profit]
          C --> D[Update minimum for future days]
          D --> E{Another day?}
          E -->|Yes| A
          E -->|No| F[Return best or zero]
        ```

        The minimum is a summary of many rejected buying candidates. Keeping a more expensive earlier candidate cannot improve a future single-sale profit.
        """,
        """
        ## Interview follow-up

        For **Longest Substring Without Repeating Characters**, why must the left pointer never move backward? Then describe how **Minimum Window Substring** changes the validity test.

        ### Check your answer

        With `abba`, the second b moves left past the earlier b. When the final a arrives, its old position is already outside the window. Use `left = max(left, last_seen[char] + 1)`; assigning the old position directly would reintroduce a repeated b. Expected time is O(n), with storage for distinct characters.

        Minimum Window tracks required multiplicities. Expand until all required counts are covered, record the candidate, then shrink while coverage remains valid. A set is insufficient when the target needs two copies of a letter. For source `AAAB` and target `AAB`, the shortest answer is `AAB`, not `AB`. Each boundary moves forward at most n times.
        """),
    'stacks': _topic(
        """
        ## Recognise the pattern

        A stack is useful when the latest unresolved item must be handled first. **Valid Parentheses** is a nesting problem: the next closing bracket must match the most recent opening bracket. Counting how many brackets exist is not enough because order carries meaning.

        ## Compare approaches and prove the choice

        Repeatedly removing adjacent matching pairs can take O(n²) time because each pass rescans or copies the string. A stack processes each character once in O(n) time and O(n) worst-case extra space. The worst memory case is a long prefix of opening brackets.

        The invariant is that the stack contains exactly the unmatched opening brackets, in encounter order. An opening bracket adds a pending obligation. A closing bracket can satisfy only the top obligation; matching an older opening would cross the nesting structure. Reject an empty stack or a mismatched top immediately. At the end, require an empty stack.

        Test an empty string, one opening bracket, a leading close, nested matches, adjacent pairs, and `([)]`. Clarify whether non-bracket characters are forbidden or should be ignored; do not silently invent a rule.

        A queue has a different order: first in, first out. Choose the structure from the obligation you must resolve, not from which collection is familiar.
        """,
        """
        ## Walk through Valid Parentheses

        Compare valid `([])` with invalid `([)]`. The first two pushes are identical; the third character separates the outcomes.

        | Character in `([])` | Stack before | Action | Stack after |
        | --- | --- | --- | --- |
        | ( | empty | Push opening | ( |
        | [ | ( | Push opening | (, [ |
        | ] | (, [ | Match and pop [ | ( |
        | ) | ( | Match and pop ( | empty |

        ```mermaid
        flowchart TD
          A[Read bracket] --> B{Opening bracket?}
          B -->|Yes| C[Push it]
          B -->|No| D{Top matches closing bracket?}
          D -->|No or empty| E[Return false]
          D -->|Yes| F[Pop matching opening]
          C --> G[Continue; at end require empty stack]
          F --> G
        ```

        For `([)]`, the closing parenthesis sees `[` on top. Reject there, even though the total opening and closing counts agree.
        """,
        """
        ## Interview follow-up

        Explain why **Implement Queue Using Stacks** can have amortized O(1) operations. Then trace **Daily Temperatures** for `[73, 71, 74]` using a monotonic stack.

        ### Check your answer

        Push new queue values onto an input stack. When the output stack is empty, transfer the entire input stack to reverse its order. Each value is pushed, transferred, and removed only a bounded number of times, so total work across m operations is O(m). One individual transfer can still cost O(m); amortized does not mean every operation is constant time.

        For temperatures, store unresolved indices with non-increasing temperatures. At index 2, temperature 74 resolves index 1 with wait 1 and index 0 with wait 2, giving `[2, 1, 0]`. Equal temperature is not warmer. Each index enters and leaves once, giving O(n) time and O(n) space despite the nested while loop.
        """),
    'linked-lists': _topic(
        """
        ## Recognise the pattern

        Linked-list questions test how you preserve access while changing connections. For **Reverse Linked List**, each node's next link must point toward its former predecessor. The input is a chain, not an array: reaching the ith node generally requires walking links rather than indexing directly.

        ## Compare approaches and prove the choice

        A baseline stores all node references in an array and reconnects them backward: O(n) time and O(n) extra space. Iterative reversal keeps only previous, current, and saved-next references: O(n) time and O(1) extra space. Recursive reversal also takes O(n) time but uses O(n) call-stack space on a chain.

        The invariant is that previous starts the correctly reversed processed prefix, while current starts the untouched suffix. Save current.next before changing it. Redirect current.next to previous, advance previous to current, then advance current to the saved next. Without the saved reference, the remaining suffix can become unreachable.

        The returned head is the last previous value, not the original head. Test no nodes, one node, two nodes, and repeated values. Reversal is about node identity, so equal values do not mean the nodes are interchangeable. State the assumption that input is acyclic; otherwise the ordinary stop-at-null loop is not a valid cycle-handling algorithm.
        """,
        """
        ## Walk through Reverse Linked List

        Start with `1 → 2 → 3 → end`, previous empty and current at node 1. The table shows state after each redirection.

        | Processed node | Saved next | Reversed prefix | Untouched suffix |
        | --- | --- | --- | --- |
        | 1 | 2 | 1 → end | 2 → 3 |
        | 2 | 3 | 2 → 1 → end | 3 |
        | 3 | end | 3 → 2 → 1 → end | empty |

        ```mermaid
        flowchart TD
          A{Current exists?} -->|No| F[Return previous as new head]
          A -->|Yes| B[Save current next]
          B --> C[Point current next to previous]
          C --> D[Move previous to current]
          D --> E[Move current to saved next]
          E --> A
        ```

        Draw the actual arrows while explaining this sequence. Writing the three assignments from memory without checking the preserved suffix is a common source of lost nodes.
        """,
        """
        ## Interview follow-up

        How does a dummy head simplify **Merge Two Sorted Lists**? In **Linked List Cycle Detection**, why compare nodes rather than their values?

        ### Check your answer

        The dummy head gives the output a stable starting anchor. Keep a tail and attach the smaller current node, moving only the selected input pointer. The output prefix stays sorted and contains exactly the nodes already consumed. Append the remaining suffix when one list ends. Time is O(n + m); relinking existing nodes uses O(1) extra space.

        Cycle detection moves one pointer one link and another two links. If they enter a cycle, the distance between them changes by one modulo the cycle length until they meet. Equal values are not enough: two different nodes may both hold 7. The method takes O(n) time and O(1) space; guard the fast pointer and its next link before advancing twice.
        """),
    'binary-search': _topic(
        """
        ## Recognise the pattern

        Binary search needs an ordered search space and a reason one half cannot contain the answer. In **Binary Search (Classic)**, the array is sorted and values are unique. Say what the current interval means before choosing loop conditions; inclusive and half-open intervals need different updates.

        ## Compare approaches and prove the choice

        A linear scan takes O(n) time and O(1) space. Binary search takes O(log n) time and O(1) iterative space because each comparison removes roughly half the remaining candidates. Sorting an unsorted array first costs O(n log n) and can lose original positions, so it is not a free improvement for one lookup.

        Use inclusive bounds left and right. The invariant is: if the target exists, it is somewhere in this interval. If the middle value is smaller, every value at or before it is also too small, so set left to mid + 1. If larger, set right to mid - 1. Every unsuccessful step strictly shrinks the interval.

        Use `left + (right - left) // 2` in languages where adding indices can overflow. Python integers avoid fixed-width overflow, but the expression still communicates intent. Test empty input, first and last positions, an absent value between elements, and a target outside both ends.
        """,
        """
        ## Walk through Binary Search (Classic)

        Find 9 in `[-1, 0, 3, 5, 9, 12]`. Indices start at zero; the expected answer is 4.

        | Left | Right | Mid | Value | Next decision |
        | --- | --- | --- | --- | --- |
        | 0 | 5 | 2 | 3 | Set left to 3 |
        | 3 | 5 | 4 | 9 | Return 4 |

        ```mermaid
        flowchart TD
          A{Left at most right?} -->|No| B[Return not found]
          A -->|Yes| C[Read middle value]
          C --> D{Compare with target}
          D -->|Equal| E[Return middle index]
          D -->|Smaller| F[Left becomes middle plus one]
          D -->|Larger| G[Right becomes middle minus one]
          F --> A
          G --> A
        ```

        Now replace the target with 4. After checking 3, then 9, then 5, the bounds cross. Returning -1 is justified because the invariant leaves no candidate position, not because a fixed number of attempts elapsed.
        """,
        """
        ## Interview follow-up

        **Search Insert Position** and **Find First and Last Position of Element in Sorted Array** need a boundary, not an arbitrary matching index. Find both boundaries of 2 in `[1, 2, 2, 2, 4]`.

        ### Check your answer

        The lower boundary is the first index with value at least 2: index 1. The upper boundary is the first index with value greater than 2: index 4. The matching range is therefore 1 through 3. Two boundary searches still take O(log n) time and O(1) working space.

        With half-open bounds `[left, right)`, start right at the array length. For a lower boundary, a qualifying middle sets right to mid; a smaller value sets left to mid + 1. Stop at equality of the bounds. Verify the resulting index is inside the array and actually matches before reporting a range. An insertion position may equal n, which is valid even though it is not a valid element index.
        """),
    'search-boundaries': _topic(
        """
        ## Recognise the pattern

        **Search in Rotated Sorted Array** has a break in global ordering, but with distinct values at least one side of the middle is sorted. Identify that side before deciding whether the target lies inside it. This is different from binary-searching a numeric answer, where a yes/no feasibility check must change in only one direction.

        ## Compare approaches and prove the choice

        Scanning is O(n) time and O(1) space. With distinct values, inspecting the sorted half removes half the candidates per step: O(log n) time and O(1) iterative space. First compare the middle with the target. If `nums[left] <= nums[mid]`, the left half is sorted. Keep it only when `nums[left] <= target < nums[mid]`; otherwise discard it. Apply the symmetric rule when the right half is sorted.

        The invariant remains that any target occurrence is inside the current interval. A sorted half supplies the evidence needed to exclude it safely. Do not use ordinary sorted-array updates across the rotation break.

        Clarify the distinct-value assumption. With duplicates such as equal left, middle, and right values, the sorted side may be ambiguous; shrinking equal boundaries can degrade the worst case to O(n). Test no rotation, one value, absent target, and a target on either side of the pivot.
        """,
        """
        ## Walk through Search in Rotated Sorted Array

        Find 0 in `[4, 5, 6, 7, 0, 1, 2]`.

        | Bounds | Middle value | Known sorted side | Decision |
        | --- | --- | --- | --- |
        | 0 through 6 | 7 at index 3 | Left: 4 through 7 | 0 is outside; keep right |
        | 4 through 6 | 1 at index 5 | Left: 0 through 1 | 0 is inside; keep index 4 |
        | 4 through 4 | 0 | Match | Return 4 |

        ```mermaid
        flowchart TD
          A[Read middle] --> B{Target matches?}
          B -->|Yes| C[Return index]
          B -->|No| D[Identify a sorted half]
          D --> E{Target inside its value range?}
          E -->|Yes| F[Keep sorted half without middle]
          E -->|No| G[Keep other half]
          F --> H[Repeat until interval empty]
          G --> H
        ```

        The choice uses value ranges as well as index positions. A diagram of indices alone does not explain why the discarded half is impossible.
        """,
        """
        ## Interview follow-up

        Connect **Find Minimum in Rotated Sorted Array** to **Koko Eating Bananas**. For piles `[3, 6, 7, 11]` and 8 hours, show why speed 4 is the smallest feasible speed.

        ### Check your answer

        For the minimum with distinct values, compare middle with the rightmost value. If middle is larger, the minimum is strictly right; otherwise it is at middle or left, so retain middle. Do not accidentally discard the minimum candidate.

        For Koko, required hours are the sum of ceiling divisions `(pile + speed - 1) // speed`. Speed 3 takes 1 + 2 + 3 + 4 = 10 hours; speed 4 takes 1 + 2 + 2 + 3 = 8. Faster speeds never require more hours, so binary-search the first feasible speed from 1 through the largest pile. Time is O(p log M) for p piles and maximum pile M, with O(1) extra space. Check whether the hour budget can cover at least one hour per nonempty pile.
        """),
    'tree-traversal': _topic(
        """
        ## Recognise the pattern

        A tree problem often asks for an answer built from its children. In **Maximum Depth of Binary Tree**, depth counts nodes on the longest root-to-leaf path. State the convention: an empty tree has depth zero, while a leaf has depth one. Confusing edge counts with node counts creates off-by-one errors.

        ## Compare approaches and prove the choice

        A baseline can enumerate all root-to-leaf paths and keep the longest; copying each path adds avoidable work and storage. A direct recurrence is `depth(node) = 1 + max(depth(left), depth(right))`. It visits each node once: O(n) time and O(h) recursion space, where h is tree height. In a chain h equals n, so the stack is not always logarithmic.

        The proof follows the tree structure. Empty children contribute zero. Assuming both child answers are correct, any path from the current node must continue through one child; choosing the longer one and adding the current node gives the correct depth.

        Breadth-first traversal counts complete levels instead. It also takes O(n) time, with O(w) queue space for maximum width w. Choose based on required output and depth limits, not a claim that one traversal is always more efficient.

        Test no root, one node, an unbalanced chain, and a broad tree. The ordinary recurrence assumes a tree, not a graph with cycles or shared nodes.
        """,
        """
        ## Walk through Maximum Depth of Binary Tree

        Root 3 has children 9 and 20; node 20 has children 15 and 7. Compute child results before their parent.

        | Node | Left depth | Right depth | Returned depth |
        | --- | --- | --- | --- |
        | 9 | 0 | 0 | 1 |
        | 15 | 0 | 0 | 1 |
        | 7 | 0 | 0 | 1 |
        | 20 | 1 | 1 | 2 |
        | 3 | 1 | 2 | 3 |

        ```mermaid
        flowchart TD
          A{Node is empty?} -->|Yes| B[Return zero]
          A -->|No| C[Compute left child depth]
          C --> D[Compute right child depth]
          D --> E[Return one plus larger child depth]
        ```

        The value 20 does not contribute twenty levels. Node values are irrelevant to this problem; only the shape determines the result.
        """,
        """
        ## Interview follow-up

        Your practices are **Invert Binary Tree** and **Same Tree**. Which recursive promises do they need, and why can equal traversal values still be insufficient to prove two trees are the same?

        ### Check your answer

        Inversion promises to return the same subtree with every left/right relationship exchanged. Swap the children and invert each, or recursively obtain inverted children and attach them in opposite positions. Time is O(n), with O(h) recursive space.

        Same Tree compares both structure and values. Two empty nodes match; one empty and one present do not; two present nodes require equal values and matching left and right subtrees. A root 1 with left child 2 differs from root 1 with right child 2, even though a traversal omitting empty markers may list the same values. Explain the base cases first, then test those two shapes. Use an explicit stack or queue when input depth makes language recursion limits a concern.
        """),
    'binary-search-trees': _topic(
        """
        ## Recognise the pattern

        A binary search tree imposes rules on whole subtrees, not just parent-child pairs. In **Validate Binary Search Tree**, every value in a left subtree must be below its ancestor and every value in a right subtree above it. Use strict comparisons for this problem's no-duplicate convention.

        ## Compare approaches and prove the choice

        Rechecking the minimum and maximum of each subtree can take O(n²) on a chain. An inorder traversal collected into a list can check strictly increasing order in O(n) time and O(n) extra storage. Passing allowed lower and upper bounds validates directly in O(n) time and O(h) call-stack space.

        The invariant is: each recursive call receives all ancestor restrictions as an open interval. A node must lie strictly inside it. The left child keeps the lower bound and receives the current value as its upper bound; the right child receives the current value as its lower bound. Combining restrictions prevents a locally valid but globally invalid subtree.

        Avoid integer sentinel values that conflict with legitimate extreme inputs. Use an explicit missing bound or a suitable unbounded representation. Test duplicates, an invalid deep descendant, extreme values, empty input, and a long chain. A valid BST is not necessarily balanced, so search height can still be O(n).
        """,
        """
        ## Walk through Validate Binary Search Tree

        Use root 5, left child 1, and right child 4 with children 3 and 6. This is invalid immediately at 4: the entire right subtree must be greater than 5.

        | Node | Allowed range | Decision |
        | --- | --- | --- |
        | 5 | No bounds | Valid; split bounds at 5 |
        | 1 | Less than 5 | Valid |
        | 4 | Greater than 5 | Invalid; return false |

        ```mermaid
        flowchart TD
          A{Node absent?} -->|Yes| B[Return true]
          A -->|No| C{Value inside ancestor bounds?}
          C -->|No| D[Return false]
          C -->|Yes| E[Validate left with smaller upper bound]
          E --> F[Validate right with larger lower bound]
          F --> G[Require both subtrees valid]
        ```

        For a subtler case, replace 4 with 7 while keeping its left child 3. The local relation 3 < 7 passes, but 3 still violates the inherited lower bound 5. This is why checking only neighbours fails.
        """,
        """
        ## Interview follow-up

        Explain **Kth Smallest Element in a BST** and **Lowest Common Ancestor of a Binary Search Tree**. What changes when many kth-element queries arrive on a tree that also receives updates?

        ### Check your answer

        Inorder traversal visits a valid BST in increasing order. Stop after k visits; an iterative stack uses O(h) space and O(h + k) time until the answer. Check that k refers to an existing rank. For frequent queries, maintain subtree sizes: compare k with left_size + 1 and descend accordingly. Updates must keep sizes correct; time is O(h), not automatically O(log n) without balancing.

        For lowest common ancestor, if both target values are smaller, go left; if both larger, go right. The first split, or a match with one target, is the ancestor under the assumption both nodes exist. If existence is not guaranteed, verify it separately. For root 5 and targets 3 and 7, the split at 5 answers immediately.
        """),
    'heaps': _topic(
        """
        ## Recognise the pattern

        Use a heap when you repeatedly need an extreme value without fully sorting everything. **Kth Largest Element in an Array** counts repeated values as separate elements. A size-k min-heap keeps the k largest values seen; its smallest member is the current kth-largest candidate.

        ## Compare approaches and prove the choice

        Sorting takes O(n log n) time and returns the kth value directly. A bounded heap takes O(n log k) time for k above one and O(k) space; for k = 1 it is a linear maximum scan. Quickselect offers expected O(n) time but can have O(n²) worst-case behavior without a stronger pivot strategy, and commonly changes the array.

        The invariant is: after enough inputs, the heap contains k largest values from the processed prefix, counting multiplicity. A new value no larger than the root cannot improve that set. A larger value replaces the root, removing the weakest retained candidate. Ties can be kept or discarded as long as k copies are represented correctly.

        A heap is not a sorted array: only the parent-child priority rule is guaranteed. Validate `1 <= k <= n`. Test duplicates, negatives, k equal to one, and k equal to n. Include the storage tradeoff when the input is a stream and cannot be revisited.
        """,
        """
        ## Walk through Kth Largest Element in an Array

        Input `[3, 2, 1, 5, 6, 4]`, k = 2. The table displays retained values in sorted order for readability; actual heap storage need not be sorted.

        | Incoming | Retained values | Action |
        | --- | --- | --- |
        | 3 | [3] | Fill heap |
        | 2 | [2, 3] | Fill heap |
        | 1 | [2, 3] | Discard 1 |
        | 5 | [3, 5] | Replace 2 |
        | 6 | [5, 6] | Replace 3 |
        | 4 | [5, 6] | Discard 4 |

        ```mermaid
        flowchart TD
          A[Read value] --> B{Heap has fewer than k?}
          B -->|Yes| C[Push value]
          B -->|No| D{Value exceeds root?}
          D -->|Yes| E[Replace root]
          D -->|No| F[Discard value]
          C --> G[After all values return root]
          E --> G
          F --> G
        ```

        The answer is 5. The maximum is 6, so a max-heap containing only one extreme would not directly maintain the requested rank.
        """,
        """
        ## Interview follow-up

        Which priority do **Last Stone Weight** and **K Closest Points to Origin** need? Why can squared distances replace square roots for closest points?

        ### Check your answer

        Last Stone Weight repeatedly removes the two largest weights, so use a max-heap or negate weights for a min-heap interface. Reinsert the positive difference when weights differ. With n stones there are O(n) rounds, giving O(n log n) time and O(n) storage.

        For closest points, distance order is unchanged by squaring nonnegative distances. Compare `x*x + y*y` and keep a size-k max-heap of the nearest candidates; its root is the farthest retained point. Time is O(n log k), with O(k) retained storage. In fixed-width languages, squared coordinates may overflow; use an appropriate numeric width. Clarify tie behavior and whether any k equally close points are acceptable.
        """),
    'heap-patterns': _topic(
        """
        ## Recognise the pattern

        **Task Scheduler** combines priority with eligibility. The task with the most remaining copies is useful only when its cooldown has expired. Keep available tasks in a max-heap and cooling tasks separately with their next valid time. Do not treat a heap as permission to run an ineligible task.

        ## Compare approaches and prove the choice

        Exhaustively trying task orders is combinatorial. For unit-time tasks, a shared cooldown c, and freely reorderable work, the minimum length is `max(N, (f - 1) * (c + 1) + m)`. Here f is the highest frequency and m is how many task types share it. The frame term creates required gaps between the most frequent tasks; the N term covers cases where other tasks fill every gap.

        Counting frequencies and evaluating the formula takes O(N + q) time and O(q) space for q task types. A heap simulation constructs a schedule explicitly. Its heap work is O(N log(q + 1)), plus any individually simulated idle slots. Jump to the next ready time when nothing is available to avoid looping through huge empty spans. Space is O(q).

        The invariant is that every heap task is currently eligible, and every cooldown entry has a future release time. If a task runs in slot t, it can run again at t + c + 1. Test cooldown zero, one task type, equally frequent types, and many different tasks. The formula does not automatically apply to different task durations or task-specific cooldowns.
        """,
        """
        ## Walk through Task Scheduler

        Tasks are `A A A B B B`, cooldown 2. A repeated task needs two intervening slots. The formula gives `(3 - 1) * 3 + 2 = 8`.

        | Slot | Action | Why allowed or required |
        | --- | --- | --- |
        | 0 | A | A becomes ready again at 3 |
        | 1 | B | B becomes ready again at 4 |
        | 2 | Idle | Neither type is ready |
        | 3, 4 | A, B | Cooldowns have expired |
        | 5 | Idle | Both remaining copies are cooling |
        | 6, 7 | A, B | Finish all tasks |

        ```mermaid
        flowchart TD
          A[Release ready cooldown entries] --> B{Available heap empty?}
          B -->|No| C[Run highest remaining count]
          C --> D[Requeue unfinished type with ready time]
          B -->|Yes| E[Jump to next ready time]
          D --> F[Advance time and repeat]
          E --> A
          F --> A
        ```
        """,
        """
        ## Interview follow-up

        How do **Find Median from Data Stream** and **Merge K Sorted Lists** use different heap invariants?

        ### Check your answer

        For a median, keep the lower half in a max-heap and the upper half in a min-heap. Every lower value must be no greater than every upper value, and heap sizes differ by at most one. Inserting 5, 2, 8 gives medians 5, 3.5, 5 after rebalancing. Insertions cost O(log n); reading the median is O(1); storing the stream costs O(n).

        For merging, keep only the next unconsumed node from each nonempty list. Pop the smallest, append it, and add its successor. Those frontier nodes include the smallest remaining value globally. Merging N nodes across k lists takes O(N log k) time and O(k) heap space. Add a stable tie breaker if equal values would otherwise require comparing node objects.
        """),
    'graph-traversal': _topic(
        """
        ## Recognise the pattern

        **Number of Islands** is a connected-component problem hidden inside a grid. Each land cell is a vertex, and horizontal or vertical neighbours are edges. The answer counts groups, not cells. Diagonal contact does not connect islands under this problem's rule.

        ## Compare approaches and prove the choice

        Starting a fresh search from every land cell without remembering visits repeats work and can overcount. Scan the grid once. When you find unvisited land, increment the count and flood-fill its entire component using DFS or BFS. Across all searches, each cell is visited at most once, so time is O(rows * columns).

        The invariant is that marked land belongs to an already counted component. A new unvisited land cell cannot belong to any fully explored earlier component, so counting it starts exactly one new island. Mark when discovering a cell, before adding its neighbours to pending work; waiting until removal can enqueue the same cell repeatedly.

        A visited set uses O(rows * columns) space in the worst case. Changing land to water avoids that set but modifies the input; the DFS stack or BFS queue may still use O(rows * columns) space. In-place marking does not make the whole algorithm constant-space.

        Test an empty grid, all water, all land, a single row, and diagonal-only contact. Recursive DFS may exceed the call-stack limit on a large connected region; an explicit worklist avoids dependence on recursion depth.
        """,
        """
        ## Walk through Number of Islands

        Use rows `1100`, `1100`, `0010`, `0001`. Scan from top left to bottom right with four-direction movement.

        | First unvisited land | Cells reached by its fill | Island count |
        | --- | --- | --- |
        | (0, 0) | (0,0), (0,1), (1,0), (1,1) | 1 |
        | (2, 2) | (2,2) | 2 |
        | (3, 3) | (3,3) | 3 |

        ```mermaid
        flowchart TD
          A[Scan next cell] --> B{Unvisited land?}
          B -->|No| A
          B -->|Yes| C[Increase island count]
          C --> D[Mark cell and start worklist]
          D --> E[Visit unmarked land neighbours]
          E --> F{Worklist empty?}
          F -->|No| E
          F -->|Yes| A
        ```

        Cells (2,2) and (3,3) touch only diagonally, so they remain separate. Changing the neighbour rule would change the graph and therefore the answer.
        """,
        """
        ## Interview follow-up

        In **Clone Graph**, why map original nodes to copies before visiting neighbours? For **Pacific Atlantic Water Flow**, why search backward from both ocean boundaries?

        ### Check your answer

        A graph may contain cycles and shared neighbours. Store the new copy immediately so a returning edge reuses it rather than recursing forever or creating duplicate copies. Key by node identity, not only a potentially repeated value. The work is O(V + E), and the map plus output require corresponding storage.

        For water flow, forward water moves to equal or lower heights. Reverse the question: from each ocean edge, which cells can reach it? Traverse to equal or higher neighbours, then intersect the two reached sets. This avoids running a separate full search from every cell and takes O(rows * columns) time and space. Explain why equal height is allowed and why the direction must reverse with the starting points.
        """),
    'graph-paths': _topic(
        """
        ## Recognise the pattern

        **Course Schedule** asks whether directed prerequisites contain a cycle. A pair `[a, b]` means an edge from b to a: completing b can unlock a. This is not a shortest-path problem, and undirected connectivity alone cannot establish whether a valid course order exists.

        ## Compare approaches and prove the choice

        Trying all course orders can require factorial work. Kahn's algorithm builds indegrees, meaning counts of unfinished prerequisites. Put every zero-indegree course into a queue, remove one, and decrement its outgoing neighbours. With adjacency lists, building and processing the graph takes O(V + E) time and O(V + E) space.

        The invariant is that a queued course has no remaining prerequisite among unprocessed courses. Removing it is therefore safe. If all V courses are removed, that removal order is valid. If unprocessed vertices remain and none has indegree zero, repeatedly following a remaining prerequisite must eventually revisit a vertex, proving a cycle.

        DFS is another linear approach, but it needs distinct unseen, active-path, and finished states. An edge to an active node signals a cycle; an edge to an already finished node does not.

        Test zero prerequisites, disconnected courses, a self-loop, a two-course cycle, and a cycle in a component away from course zero. A search starting only at one vertex misses disconnected failures.
        """,
        """
        ## Walk through Course Schedule

        For four courses, use prerequisites `[[1,0], [2,0], [3,1], [3,2]]`. Initial indegrees are `[0,1,1,2]`.

        | Removed course | Changed indegrees | Queue afterward | Removed total |
        | --- | --- | --- | --- |
        | 0 | 1 becomes 0; 2 becomes 0 | 1, 2 | 1 |
        | 1 | 3 becomes 1 | 2 | 2 |
        | 2 | 3 becomes 0 | 3 | 3 |
        | 3 | No outgoing edges | empty | 4 |

        ```mermaid
        flowchart TD
          A[Count incoming prerequisites] --> B[Queue every zero-indegree course]
          B --> C{Queue has a course?}
          C -->|Yes| D[Remove it and decrement neighbours]
          D --> E[Queue neighbours that just reach zero]
          E --> C
          C -->|No| F{Removed count equals total?}
          F -->|Yes| G[All courses possible]
          F -->|No| H[Cycle remains]
        ```
        """,
        """
        ## Interview follow-up

        Why do **Number of Connected Components** and **Network Delay Time** need different tools? Explain when Dijkstra's greedy finalisation is safe.

        ### Check your answer

        Connected Components is undirected grouping. Union-find starts with V groups; each edge joining different roots reduces the count by one. Path compression with union by rank or size gives almost-constant amortized operations, commonly written O(alpha(V)). Repeated edges within one group do not reduce the count again.

        Network Delay has nonnegative edge weights. Dijkstra repeatedly takes the smallest current distance and relaxes outgoing edges; nonnegative costs prevent a later route through farther unsettled vertices from improving that settled distance. A heap implementation with stale entries skipped is commonly O((V + E) log V) for a simple graph, with O(V + E) storage. Return the largest shortest-path distance only if every vertex is reachable; otherwise return the specified failure value. Plain BFS works only when edge costs are equal.
        """),
    'backtracking': _topic(
        """
        ## Recognise the pattern

        **Subsets** asks for every valid choice, not one best score. Each distinct input element creates an include-or-exclude decision. Backtracking keeps one partial result, explores a choice, and restores the previous state before trying a sibling choice. The restoration is part of correctness.

        ## Compare approaches and prove the choice

        Enumerating all bit masks is a clear baseline and already matches the unavoidable number of outputs. A recursive decision tree also has 2^n leaves. Returning independent lists takes O(n * 2^n) total time and output storage in the worst case because copying the subsets itself costs work. The recursion and current path use O(n) extra space excluding output.

        The invariant is: at recursion depth i, the path contains exactly the chosen values among the first i input positions. The include branch adds position i; the exclude branch does not. Every subset has one unique sequence of these decisions, so all are produced once when inputs are distinct.

        Save a copy of the path when emitting a result. Saving the same mutable list repeatedly makes later pop operations change earlier outputs. Empty input has one subset, the empty subset, rather than no subsets.

        If values repeat, position-based decisions can produce equal value subsets. Clarify whether duplicates are permitted or whether sorting and duplicate-skipping rules are required. Do not add those rules to the distinct-input problem without explaining the changed contract.
        """,
        """
        ## Walk through Subsets

        Use `[1, 2]` and explore the exclude branch first. Record a result only after both positions have decisions.

        | Decision for 1 | Decision for 2 | Saved copy |
        | --- | --- | --- |
        | Exclude | Exclude | [] |
        | Exclude | Include | [2] |
        | Include | Exclude | [1] |
        | Include | Include | [1, 2] |

        ```mermaid
        flowchart TD
          A[Start with empty path] --> B[Exclude 1]
          A --> C[Include 1]
          B --> D[Exclude 2: save empty]
          B --> E[Include 2: save 2]
          C --> F[Exclude 2: save 1]
          C --> G[Include 2: save 1 and 2]
        ```

        After exploring an include branch, remove the value you added. Otherwise, the next branch begins with someone else's choices and the path invariant is broken.
        """,
        """
        ## Interview follow-up

        How do **Permutations** and **Combination Sum** change the state? Explain why unrestricted reuse must be paired with a stopping rule in Combination Sum.

        ### Check your answer

        A permutation chooses an unused input index at each depth, so it needs a used set or in-place swaps. There are n! results, each length n, giving O(n * n!) output work for distinct inputs. Undo the used marker or swap when returning.

        Combination Sum tracks remaining target and a starting candidate index. Choosing the same index again allows reuse; restricting future choices to that index or later prevents reordered duplicates. With positive candidates, subtracting a chosen value moves the target toward zero; a negative remainder stops a branch. For candidates `[2,3]` and target 7, `[2,2,3]` is one result, not three reordered results. Zero or negative candidates invalidate the simple progress argument and require a different contract or algorithm.
        """),
    'constraint-search': _topic(
        """
        ## Recognise the pattern

        **Word Search** asks whether one path spells a word under movement and reuse constraints. The state includes the current cell, the next character position, and cells already used on this path. A global permanently visited set is wrong because another starting path may legitimately use the same cell.

        ## Compare approaches and prove the choice

        Enumerating arbitrary cell sequences wastes work on non-neighbours and wrong characters. Backtracking starts only at matching first letters, moves only to valid neighbours, and rejects mismatches immediately. For R rows, C columns, and word length L, a simple upper bound is O(RC * 4^L) time. Avoiding the immediately previous cell sharpens later branching to at most three, but worst-case search remains exponential.

        The invariant is: the marked cells form exactly the current valid prefix path, and no cell appears twice in it. Mark before exploring children and unmark when returning, including an early successful return if the board must remain unchanged. The path and recursion require O(L) space when L fits within the board; a separate full visited array uses O(RC).

        Reject words longer than the number of cells. A character-frequency check can reject impossible inputs early, though it cannot prove a path exists. Test repeated letters, a path that would need cell reuse, a diagonal-only match, an empty board, and the agreed meaning of an empty word.
        """,
        """
        ## Walk through Word Search

        On rows `ABCE`, `SFCS`, `ADEE`, search for `ABCCED`. Coordinates start at zero.

        | Word position | Needed letter | Chosen cell | Used path length |
        | --- | --- | --- | --- |
        | 0 | A | (0,0) | 1 |
        | 1 | B | (0,1) | 2 |
        | 2 | C | (0,2) | 3 |
        | 3 | C | (1,2) | 4 |
        | 4 | E | (2,2) | 5 |
        | 5 | D | (2,1) | 6 |

        ```mermaid
        flowchart TD
          A[Try cell for next letter] --> B{In bounds, unused, matching?}
          B -->|No| C[Reject this branch]
          B -->|Yes| D[Mark cell in current path]
          D --> E{Last letter matched?}
          E -->|No| F[Explore four neighbours]
          E -->|Yes| G[Record success]
          F --> H[Unmark before returning]
          G --> H
        ```
        """,
        """
        ## Interview follow-up

        How do **Palindrome Partitioning** and **N-Queens** reject a partial choice early? Give a concrete state-restoration mistake for either problem.

        ### Check your answer

        Partitioning chooses the next substring only if it is a palindrome. For `aab`, valid results are `[a,a,b]` and `[aa,b]`. Precomputing palindrome ranges costs O(n²) time and space and makes later validity checks constant time; enumerating the partitions still has exponential output in the worst case. A forgotten pop can leave `aa` inside a sibling partition.

        N-Queens places one queen per row and tracks occupied columns and diagonals `row - column` and `row + column`. Reject a candidate if any marker is occupied; after recursion, remove all three markers. Equal diagonal keys mean an attack even when columns differ. This prunes many impossible boards but is still combinatorial search, not a polynomial algorithm. Explain which constraints are checked before descending and which markers must be undone together.
        """),
    'dynamic-programming': _topic(
        """
        ## Recognise the pattern

        **Climbing Stairs** asks for the number of ways to reach a state. Many longer paths share the same smaller remaining problem. Dynamic programming saves those answers instead of recomputing them. First define precisely what dp[i] means; a recurrence without a state meaning is easy to apply incorrectly.

        ## Compare approaches and prove the choice

        Recursively choosing a one-step or two-step move repeats the same subproblems and takes exponential time, bounded by O(2^n), with O(n) stack depth. Memoization stores each answer once, giving O(n) arithmetic operations and O(n) storage. Bottom-up calculation uses the previous two values only, reducing stored counters to O(1).

        Define dp[i] as the number of distinct move sequences reaching step i. The last move comes from i - 1 or i - 2. These groups are disjoint and cover every valid sequence, so `dp[i] = dp[i-1] + dp[i-2]`. Set dp[0] = 1 for the one empty sequence and dp[1] = 1. Explain the zero-step convention even if the supplied problem starts at n = 1.

        Test n = 1, n = 2, and the smallest value using the recurrence. With very large n, counts grow large: O(n) here uses the interview's unit-cost arithmetic model. Python's arbitrary-size integers use more bits and make addition costs grow; fixed-width languages need an overflow policy.
        """,
        """
        ## Walk through Climbing Stairs

        For n = 5, build the answer from smaller steps rather than listing every route.

        | Step i | Previous counts used | dp[i] |
        | --- | --- | --- |
        | 0 | Empty sequence | 1 |
        | 1 | One single step | 1 |
        | 2 | 1 + 1 | 2 |
        | 3 | 2 + 1 | 3 |
        | 4 | 3 + 2 | 5 |
        | 5 | 5 + 3 | 8 |

        ```mermaid
        flowchart TD
          A[Start with ways for steps zero and one] --> B[Add previous two counts]
          B --> C[Current count becomes next saved value]
          C --> D{Reached requested step?}
          D -->|No| B
          D -->|Yes| E[Return current count]
        ```

        When using two variables, compute the new sum before overwriting the older values. Otherwise both variables may accidentally refer to the same already-updated count.
        """,
        """
        ## Interview follow-up

        How do **House Robber** and **Coin Change** change the recurrence's meaning? Work through amount 6 with coin values `[1, 3, 4]`.

        ### Check your answer

        House Robber maximizes value rather than counting paths. For each house, choose between skipping it and taking its value plus the best result before its neighbour. For `[2,7,9,3,1]`, the optimum is 12 from 2 + 9 + 1. The recurrence must preserve the no-adjacent constraint.

        Coin Change minimizes the number of coins: `dp[a] = 1 + min(dp[a-c])` over usable coins c. Start dp[0] at zero and unreachable amounts at infinity. For 6, choosing the largest coin first gives 4 + 1 + 1, while DP finds 3 + 3 using two coins. For amount A and C coin types, time is O(A*C) and space O(A). State that coin values are positive; zero or negative values break the simple smaller-state dependency.
        """),
    'dp-grids': _topic(
        """
        ## Recognise the pattern

        **Longest Common Subsequence** compares two prefixes. A subsequence preserves order but may skip characters; it need not occupy consecutive positions. Two changing prefix lengths create a two-dimensional state. Define dp[i][j] as the best length using the first i characters of one string and the first j of the other.

        ## Compare approaches and prove the choice

        A brute-force method enumerates subsequences of one string and checks them against the other, giving exponential work. Prefix DP fills (m + 1) * (n + 1) states in O(mn) time and O(mn) space. Keeping only the previous and current row reduces length-only storage to O(min(m,n)) when the shorter string is the column dimension.

        Empty prefixes have answer zero. If the last characters match, use one plus the diagonal prefix answer. If they differ, a common subsequence cannot use both as a matched final pair, so take the better answer from dropping one last character or the other. This covers all optimal possibilities.

        The invariant is that every dependency is complete before its cell is filled. Row-major order provides the previous row, previous column, and diagonal. Reconstructing the actual subsequence needs decisions or a separate reconstruction strategy; two-row storage alone does not retain every backward choice.

        Test either string empty, no common letters, repeated letters, identical strings, and `abc` versus `ac`, whose answer is two despite the gap.
        """,
        """
        ## Walk through Longest Common Subsequence

        Compare `abcde` with `ace`. Rows represent prefixes of the first string; columns represent prefixes of the second.

        | Prefix | empty | a | ac | ace |
        | --- | --- | --- | --- | --- |
        | empty | 0 | 0 | 0 | 0 |
        | a | 0 | 1 | 1 | 1 |
        | ab | 0 | 1 | 1 | 1 |
        | abc | 0 | 1 | 2 | 2 |
        | abcd | 0 | 1 | 2 | 2 |
        | abcde | 0 | 1 | 2 | 3 |

        ```mermaid
        flowchart TD
          A[Choose next prefix pair] --> B{Last characters equal?}
          B -->|Yes| C[Diagonal value plus one]
          B -->|No| D[Maximum of above and left]
          C --> E[Store cell and continue]
          D --> E
        ```

        The answer is the bottom-right 3, represented by `ace`. The table stores lengths, not the strings themselves, avoiding repeated string construction at each cell.
        """,
        """
        ## Interview follow-up

        Why does one-dimensional **0/1 Knapsack** update capacities backward? How does **Edit Distance** differ from LCS when the last characters do not match?

        ### Check your answer

        For a 0/1 item, each item may be used once. Descending capacities ensure `dp[capacity-weight]` still belongs to the previous item layer. Updating upward can reuse the same item repeatedly. With one item of weight 2 and value 3, capacity 4 should yield 3, not 6. Time is O(items * capacity), which is pseudopolynomial because capacity's numeric value can be large relative to its encoded length.

        Edit Distance minimizes insertions, deletions, and substitutions. For a mismatch, take one plus the minimum of left, above, and diagonal. Empty-prefix base cases are their lengths, not zero. Changing `cat` to `cut` costs one substitution. As with LCS, O(mn) time is typical, and reduced rows suffice for distance alone but not a naive full edit-script backtrack.
        """),
    'greedy': _topic(
        """
        ## Recognise the pattern

        A greedy algorithm commits to a local choice without exploring every future combination. That needs a proof, not just a successful example. In **Assign Cookies**, satisfy the least-demanding remaining child with the smallest remaining cookie that is large enough. Saving larger cookies preserves options for more demanding children.

        ## Compare approaches and prove the choice

        Trying assignments recursively creates a combinatorial search. Sorting children's needs and cookie sizes allows a two-pointer scan. With n children and m cookies, time is O(n log n + m log m), followed by O(n + m) scanning. The scan uses O(1) additional variables, but include sorting's implementation-dependent memory and whether input mutation is allowed.

        The exchange argument explains why the choice is safe. If an optimal assignment gives the least-demanding child a larger suitable cookie, exchange it with the smallest suitable one. If that smaller cookie was assigned elsewhere, the displaced child can use the larger cookie it replaces. No satisfied child is lost. Repeating this argument supports every greedy step.

        A cookie too small for the least-demanding remaining child cannot satisfy any later child, so discard it. When a cookie fits, advance both pointers. Do not use the same cookie twice.

        Test no cookies, no children, equal needs, extra tiny cookies, and more children than cookies. The proof assumes each child needs only one cookie and only size matters; adding allergies or multiple-cookie combinations changes the problem.
        """,
        """
        ## Walk through Assign Cookies

        Needs are `[1, 2, 3]` and cookies are `[1, 1]`, already sorted.

        | Current need | Current cookie | Decision | Satisfied count |
        | --- | --- | --- | --- |
        | 1 | First 1 | Assign; advance both | 1 |
        | 2 | Second 1 | Too small; discard cookie | 1 |
        | 2 | No cookie remains | Stop | 1 |

        ```mermaid
        flowchart TD
          A[Sort needs and sizes] --> B{Child and cookie remain?}
          B -->|No| C[Return satisfied count]
          B -->|Yes| D{Cookie meets smallest remaining need?}
          D -->|Yes| E[Assign and advance child]
          D -->|No| F[Discard undersized cookie]
          E --> G[Advance cookie]
          F --> G
          G --> B
        ```

        There is no alternative assignment satisfying two children: both available cookies have size one, while only one child accepts that size. The trace shows the result; the exchange argument explains the general algorithm.
        """,
        """
        ## Interview follow-up

        What fact makes **Jump Game** greedy? In **Gas Station**, why can a failed starting segment be skipped rather than trying every station inside it?

        ### Check your answer

        Jump Game keeps the farthest reachable index after scanning reachable positions. If the next index exceeds that boundary, no earlier jump can reach it. Otherwise update `farthest = max(farthest, i + nums[i])`. This takes O(n) time and O(1) space. For `[3,2,1,0,4]`, reach never passes index 3, so the last index is unreachable.

        Gas Station first requires total gas at least total cost. Track the running balance from a candidate start. If it becomes negative at j, every start inside that failed segment also fails by j: earlier partial balances from the candidate were nonnegative, so subtracting them cannot repair the final deficit. Restart at j + 1. This gives O(n) time and O(1) space. Explain the total-feasibility check as well as the restart rule; either alone is insufficient.
        """),
    'intervals': _topic(
        """
        ## Recognise the pattern

        **Merge Intervals** asks for the union of ranges. Sort by starting position so future ranges cannot begin before already processed ranges. State whether endpoints are closed: in this exercise, `[1,3]` and `[3,5]` overlap and merge. Other scheduling problems may treat an ending time as immediately reusable.

        ## Compare approaches and prove the choice

        Repeatedly checking and combining every pair can take quadratic or worse work if implemented with rescans. Sorting then scanning takes O(n log n) time, with O(n) result storage in the worst case. Extra working memory beyond the result depends on sorting and whether the input is copied.

        The invariant is that the output is a sorted, non-overlapping union of all processed input ranges. Only its last interval can overlap the next input: all earlier output intervals end before that last interval starts. If the next start is at most the current end, extend the end to the maximum of both ends. Otherwise append a new interval.

        Never replace the end blindly with the next end: a nested interval such as `[2,3]` must not shrink `[1,10]`. Decide whether modifying original interval objects is permitted, since reusing and editing them may surprise a caller.

        Test empty input, one interval, touching endpoints, identical ranges, complete nesting, and unsorted ranges. Validate or clearly assume that each start is no greater than its end.
        """,
        """
        ## Walk through Merge Intervals

        Input: `[[1,3], [2,6], [8,10], [15,18]]`.

        | Next interval | Current output | Decision |
        | --- | --- | --- |
        | [1,3] | [] | Start first output interval |
        | [2,6] | [[1,3]] | 2 <= 3; extend end to 6 |
        | [8,10] | [[1,6]] | Gap; append [8,10] |
        | [15,18] | [[1,6], [8,10]] | Gap; append [15,18] |

        ```mermaid
        flowchart TD
          A[Sort intervals by start] --> B[Read next interval]
          B --> C{Overlaps last output interval?}
          C -->|Yes| D[Extend end using maximum]
          C -->|No| E[Append a separate interval]
          D --> F[Continue until all intervals processed]
          E --> F
        ```

        The result preserves covered positions, not the number of original meetings or records. If the caller needs original identities, a union alone loses that information.
        """,
        """
        ## Interview follow-up

        Why do **Non-overlapping Intervals** and **Meeting Rooms II** require different answers from merging? Explain meetings `[0,30]`, `[5,10]`, and `[15,20]`.

        ### Check your answer

        Minimum removals keeps as many compatible intervals as possible. Choosing the earliest finishing compatible interval leaves maximum room for later intervals; return total count minus kept count. Under the usual scheduling convention, a meeting starting exactly when another ends does not conflict. Sorting by end gives O(n log n) time.

        Meeting Rooms asks for maximum simultaneous occupancy, not the number of merged groups. The three meetings form one merged union but require two rooms. Sort by start and maintain a min-heap of active ending times. Remove every end at or before the next start, add the new end, and track the maximum heap size. This is O(n log n) time and O(n) space. Confirm the boundary convention before choosing less-than versus less-than-or-equal comparisons.
        """),
    'bits': _topic(
        """
        ## Recognise the pattern

        **Single Number** contains a strong promise: every value occurs twice except one. XOR is useful because each bit tracks parity, meaning whether the number of ones encountered is odd or even. It combines the whole input while cancelling exactly the promised pairs.

        ## Compare approaches and prove the choice

        A frequency map takes expected O(n) time and O(n) storage. Sorting and scanning pairs takes O(n log n) time, with sorting-dependent memory. XOR uses one accumulator and O(n) fixed-width operations. It does not need to change the array.

        The identities are `x ^ x = 0` and `x ^ 0 = x`. XOR is associative and commutative, so paired values cancel regardless of their positions. The invariant is: the accumulator equals the XOR of the processed prefix. After the final item, only the unpaired value remains under the stated input promise.

        This is O(1) extra machine words when values have fixed width. Python integers can grow beyond a machine word, so bit-operation cost and stored bits depend on integer size. State the numeric model rather than claiming infinite-sized values are constant-cost.

        Test a singleton, zero as the unique value, negatives, and distant pairs. If two values occur once, XOR returns their combined XOR rather than either answer; it does not validate the input promise. A duplicate appearing three times also violates the cancellation argument.
        """,
        """
        ## Walk through Single Number

        Input `[4, 1, 2, 1, 2]`. Show three binary places for this nonnegative example.

        | Value | Accumulator before | XOR result |
        | --- | --- | --- |
        | 4 = 100 | 000 | 100 = 4 |
        | 1 = 001 | 100 | 101 = 5 |
        | 2 = 010 | 101 | 111 = 7 |
        | 1 = 001 | 111 | 110 = 6 |
        | 2 = 010 | 110 | 100 = 4 |

        ```mermaid
        flowchart TD
          A[Set accumulator to zero] --> B[Read next integer]
          B --> C[XOR integer into accumulator]
          C --> D{More integers?}
          D -->|Yes| B
          D -->|No| E[Return remaining unpaired value]
        ```

        Intermediate values such as 7 do not need to occur in the input. The accumulator is a bit summary, not a candidate that must always be an existing element.
        """,
        """
        ## Interview follow-up

        For **Number of 1 Bits**, explain `x & (x - 1)`. Then derive the recurrence used by **Counting Bits** for every number from zero through n.

        ### Check your answer

        For nonnegative x, subtracting one flips its lowest set bit to zero and turns lower zeros into ones. AND with the original clears exactly that lowest set bit. For 12 (`1100`), the sequence is 12 → 8 → 0, so there are two set bits. Work is O(number of set bits), bounded by the chosen bit width. An unbounded negative Python integer does not reach zero this way; define a fixed-width mask or reject unsupported signed input.

        Counting Bits uses `count[i] = count[i >> 1] + (i & 1)`: the right shift removes the last bit, and the AND says whether that bit was one. Results through 5 are `[0,1,1,2,1,2]`. This takes O(n) fixed-width work and O(n) output storage. The recurrence reuses answers, unlike recounting every integer independently.
        """),
    'tries': _topic(
        """
        ## Recognise the pattern

        A trie stores shared character prefixes as paths. **Implement Trie** needs both exact-word search and prefix search, so reaching a path is not enough to prove a complete word exists. Each node needs a separate terminal marker alongside its child links.

        ## Compare approaches and prove the choice

        A set is a good baseline for exact words, but finding whether any stored word has a prefix may require scanning many words. A trie follows only the prefix characters. With expected constant-time child-map lookup, inserting or looking up L characters takes expected O(L) time. Total nodes are at most one plus the total number of inserted characters, before sharing reduces that count.

        Fixed-alphabet arrays make child access direct but can waste many empty slots. Child dictionaries store sparse branches but add per-node overhead. A trie is not automatically smaller than a word set; memory layout and prefix sharing matter.

        The invariant is that the current node represents exactly the characters consumed so far. Missing a required edge proves failure. After consuming all input, starts_with succeeds because the path exists; search additionally requires the terminal marker. Inserting an existing word can simply retain the marker without adding duplicates.

        Test a complete word, its uninserted prefix, a longer absent extension, repeated insertion, and two words sharing a prefix. Define the empty-string contract: allowing insertion can mark the root terminal, while an empty prefix naturally matches the root path.
        """,
        """
        ## Walk through Implement Trie

        Insert `apple`. The root connects through a, p, p, l, e; only e is terminal initially.

        | Operation | Path exists? | Final terminal marker | Result |
        | --- | --- | --- | --- |
        | search apple | Yes | True | True |
        | search app | Yes | False | False |
        | starts_with app | Yes | Irrelevant | True |
        | insert app | Yes | Set app node to true | Both words now stored |
        | search apps | No s edge | Not reached | False |

        ```mermaid
        flowchart TD
          A[Start at root] --> B{Required child exists?}
          B -->|No| C[Search fails]
          B -->|Yes| D[Follow edge and consume character]
          D --> E{Characters remain?}
          E -->|Yes| B
          E -->|No| F{Exact search or prefix search?}
          F -->|Exact| G[Require terminal marker]
          F -->|Prefix| H[Return true]
        ```

        Insertion creates missing edges instead of failing at them. Keeping insertion and search behavior distinct avoids accidentally changing the trie during a read.
        """,
        """
        ## Interview follow-up

        In **Design Add and Search Words Data Structure**, a dot matches any one character. After adding `bad`, `dad`, and `mad`, explain searches `pad`, `.ad`, and `b..`. What happens to complexity?

        ### Check your answer

        `pad` fails because the root has no p edge. `.ad` branches across existing root children; the b branch reaches a terminal word, so it can return true. `b..` first follows b and then explores one child per dot level, accepting only when the whole pattern ends at a terminal node.

        A literal character follows one edge; a dot may explore every child. Therefore wildcard search is not generally O(L). With alphabet size A, all-dot patterns can explore exponentially many prefixes, bounded by the nodes actually present and visited in the trie. Recursive working depth is O(L). Never allow a dot to match zero characters or several characters: that would be a different pattern language. Test `.a` to confirm that a matching prefix without a complete word is rejected.
        """),
}


def lesson(identifier: str) -> dict:
    """Return independent depth content without touching learner state."""
    if not isinstance(identifier, str) or identifier not in _TOPICS:
        raise ValueError('Choose a topic from the DSA practice course.')
    return deepcopy(_TOPICS[identifier])
