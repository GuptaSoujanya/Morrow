"""Small, public introductions for the existing DSA practice sequence."""

# Each introduction has its own tiny example. The saved interview questions and
# their stable IDs remain separate, so improving the teaching never resets work.
_TOPICS = {
    'hashing': (
        'Remember what you have already seen',
        'A list keeps items in order. A set remembers each different item once. '
        'Use a set when you need to ask, “Have I seen this before?” '
        'A dictionary saves a name and its value, such as apple: 3.',
        'List: `[2, 4, 2]`. We want to know if a number appears again.',
        ['Start with an empty set.', 'Read 2. It is new, so remember it.',
         'Read 4. It is new, so remember it.', 'Read 2 again. We already have 2. The answer is yes.'],
        'Does `[3, 5, 3]` have a repeated number? What about `[3, 5, 7]`?',
        'The first list repeats 3, so the answer is yes. The second has no repeats, so the answer is no.',
        {'Duplicate': 'an item that appears again', 'Set': 'a collection with no repeated items',
         'Hash map': 'another name for a dictionary; it connects a name to a value'}),
    'array-patterns': (
        'Put similar words together',
        'Sometimes different items belong in the same group. Give similar items the same label. '
        'A dictionary can keep the group under that label.',
        'Words: `eat`, `tea`, `cat`. Group words that use the same letters.',
        ['Put the letters of eat in order: aet.', 'Put the letters of tea in order: aet.',
         'Put the letters of cat in order: act.', 'eat and tea share aet. Keep them together. cat stays in another group.'],
        'Group `bat`, `tab`, and `dog` using the same steps.',
        'The groups are [bat, tab] and [dog]. bat and tab both have the label abt.',
        {'Anagram': 'a word made by changing the order of the same letters',
         'Key': 'the label used to find a group in a dictionary'}),
    'two-pointers': (
        'Look from both ends',
        'A pointer here means the position you are looking at in a list. '
        'Use two positions to compare items. Move one or both after each check.',
        'Is `level` the same when read from either end?',
        ['Compare the first and last letters: l and l match.',
         'Move both positions inward: e and e match.', 'Only v remains in the middle. All pairs matched. The answer is yes.'],
        'Use these steps to check `radar` and `robot`.',
        'radar matches from both ends. robot does not: the first r and last t differ.',
        {'Pointer': 'a position in a list or word', 'Palindrome': 'a word or list that reads the same from both ends'}),
    'sliding-window': (
        'Move a small group along a list',
        'A window is a group of items next to each other. Move it one place at a time. '
        'Keep a useful total instead of counting every item again.',
        'List: `[2, 1, 4, 3]`. Find the largest total of two neighbours.',
        ['The first window is [2, 1]. Its total is 3.',
         'Remove 2 and add 4. The next total is 3 − 2 + 4 = 5.',
         'Remove 1 and add 3. The next total is 5 − 1 + 3 = 7.', 'The largest total is 7, from [4, 3].'],
        'Find the largest total of two neighbours in `[1, 5, 2]`.',
        'The totals are 6 and 7. The answer is 7, from [5, 2].',
        {'Window': 'a group of neighbouring items', 'Slide': 'move the group one place'}),
    'stacks': (
        'Use the last item first',
        'A stack works like a pile of plates. You add a plate on top. '
        'You take the top plate first. A queue is different: the first person in line goes first.',
        'You type A, then B, then C. Undo the last two actions.',
        ['Save the actions in order: [A, B, C].', 'Undo removes C, the last action.',
         'Undo again removes B. Only A remains.'],
        'A stack contains [red, blue, green]. Which item leaves first?',
        'green leaves first because it was added last.',
        {'Stack': 'a collection where the last item added leaves first',
         'Push': 'add an item on top', 'Pop': 'remove the top item',
         'Queue': 'a line where the first item added leaves first'}),
    'linked-lists': (
        'Follow a chain of items',
        'A linked list is a chain. Each part holds a value and a link to the next part. '
        'Start at the first part and follow the links.',
        'Chain: `2 → 5 → 8 → end`. Find how many values it holds.',
        ['Start at 2. Count 1.', 'Follow its link to 5. Count 2.',
         'Follow the next link to 8. Count 3.', 'The next link says end. Stop. There are 3 values.'],
        'In `4 → 7 → 9 → end`, what value comes after 7?',
        '9 comes after 7. Follow the link stored with 7.',
        {'Node': 'one part holding a value and a link', 'Head': 'the first node', 'Next': 'the link to the following node'}),
    'binary-search': (
        'Remove half of the choices',
        'Binary search finds a value in a sorted list. Sorted means the values are in order. '
        'Check the middle. The order tells you which half can be skipped.',
        'Find 8 in `[2, 4, 6, 8, 10]`.',
        ['The middle value is 6.', '8 is larger than 6. Ignore 2, 4, and 6.',
         'Check the remaining [8, 10]. The first value is 8. Found it.'],
        'Find 2 in the same list. Which side of 6 should you keep?',
        'Keep the left side [2, 4]. 2 is smaller than 6. Then check 2.',
        {'Sorted': 'put in order', 'Binary search': 'search by removing about half the choices each step'}),
    'search-boundaries': (
        'Find where the answer changes',
        'Some search questions ask for the first value that passes a check. '
        'Binary search works if smaller choices all fail and larger choices all pass.',
        'Box sizes are `[1, 2, 3, 4, 5]`. An item needs size 4 or larger.',
        ['Check size 3. It is too small.', 'Sizes 1 and 2 also fail. Look at [4, 5].',
         'Size 4 fits. Nothing smaller fits. The answer is 4.'],
        'If the item needs size 2, what is the smallest box that fits?',
        'Size 2. Size 1 fails, and all sizes from 2 upward fit.',
        {'Boundary': 'the place where a result changes', 'Check': 'a question with a yes or no result'}),
    'tree-traversal': (
        'Visit every branch',
        'A tree is a set of items joined like branches. It starts at one item. '
        'Each item can lead to child items. Visiting means reading or using an item.',
        'A has children B and C. B has child D. Visit one level at a time.',
        ['Visit A first.', 'Save A’s children, B and C, in a queue.',
         'Visit B, then C. B adds D to the queue.', 'Visit D. The order is A, B, C, D.'],
        'If C also has child E, what is the visit order?',
        'A, B, C, D, E. Visit both children before their children.',
        {'Root': 'the starting item', 'Child': 'an item directly below another item',
         'Breadth-first search': 'visit one level at a time', 'Queue': 'a line where the first item added leaves first'}),
    'binary-search-trees': (
        'Choose the smaller or larger branch',
        'In a binary search tree, each item has at most two children. '
        'For this example, smaller values go left and larger values go right. There are no repeats.',
        'The top value is 5. Its left child is 2 and its right child is 8. Find 8.',
        ['Start at 5.', '8 is larger than 5. Follow the right link.', 'The next value is 8. Stop.'],
        'Where should you look for 2 from the top value 5?',
        'Go left because 2 is smaller than 5. The left child is 2.',
        {'Binary': 'each item has at most two children here', 'Search tree': 'a tree whose value order helps you search'}),
    'heaps': (
        'Take the most urgent item',
        'A priority queue chooses the item with the highest priority. It does not always choose the oldest item. '
        'A heap is one way to build it. A min-heap keeps the smallest value at the top.',
        'Tasks have priority numbers 3, 1, and 2. A smaller number means more urgent.',
        ['Add all three tasks.', 'Take priority 1 first.', 'The smallest remaining number is 2. Take it next.', 'Take priority 3 last.'],
        'Priorities are 5, 2, and 4. Which leaves a min-heap first?',
        '2 leaves first because it is the smallest value.',
        {'Priority': 'how soon an item should be handled', 'Min-heap': 'a structure that keeps the smallest item ready to take'}),
    'heap-patterns': (
        'Remember only the best few values',
        'A stream is information that arrives one item at a time. '
        'If you only need the largest two values, you can keep two instead of the whole stream.',
        'Values arrive as 4, 1, 7, 3. Keep the largest two seen so far.',
        ['After 4 and 1, keep [1, 4].', '7 arrives. Drop 1, the smallest. Keep [4, 7].',
         '3 arrives. It is smaller than 4. Keep [4, 7].'],
        'Now 6 arrives. Which two values should stay?',
        'Keep [6, 7]. Drop 4. A small min-heap can keep the smallest saved value ready to compare.',
        {'Stream': 'items arriving over time', 'Min-heap': 'a structure that keeps its smallest saved value ready'}),
    'graph-traversal': (
        'Follow connections without getting stuck',
        'A graph describes things and their connections. A map of towns and roads is a graph. '
        'Remember the places you have visited so you do not visit them forever.',
        'A connects to B and C. B also connects to C. Start at A.',
        ['Visit A and mark it as seen.', 'Visit B and mark it as seen.',
         'Visit C and mark it as seen.', 'If a road leads to a seen place, skip it. All three places were visited.'],
        'C has a road back to A. Should you visit A again?',
        'No. A is already marked as seen. Skipping it prevents a loop.',
        {'Graph': 'items and the connections between them', 'Edge': 'one connection', 'Visited': 'already seen'}),
    'graph-paths': (
        'Do tasks in a safe order',
        'Some tasks must wait for others. Draw an arrow from each earlier task to the task that needs it. '
        'Start with a task that has nothing left to wait for.',
        'Make a sandwich: get bread → add filling → close sandwich.',
        ['Get bread first. It has no earlier task.', 'Add filling after the bread is ready.',
         'Close the sandwich after adding the filling.'],
        'A needs B first, and B needs A first. Can either task start?',
        'No. Each waits for the other. This loop is called a cycle. The requirements must change.',
        {'Dependency': 'a task that must finish before another can start',
         'Topological order': 'an order that puts each required task first', 'Cycle': 'a chain that loops back to its start'}),
    'backtracking': (
        'Try a choice, then undo it',
        'Backtracking explores choices one at a time. When one path is finished, undo the last choice. '
        'Then try another. It helps list all possible answers.',
        'Make all two-letter words using A or B at each place.',
        ['Choose A first. Add A: AA. Save it.', 'Undo the last letter. Add B: AB. Save it.',
         'Go back to the first place and choose B.', 'Try A, then B at the second place. Save BA and BB.'],
        'How many words did we make?',
        'Four: AA, AB, BA, BB. We tried both choices at each place.',
        {'Backtrack': 'undo a choice and try another', 'Choice': 'one option you can try'}),
    'constraint-search': (
        'Stop a choice when it breaks a rule',
        'A constraint is a rule an answer must follow. While trying choices, check the rules early. '
        'Stop a path as soon as it cannot work.',
        'Pick two different numbers from [1, 2, 3, 4, 5] whose total is 4. Try smaller numbers first.',
        ['Start with 1. Adding 2 gives 3; adding 3 gives 4. Save [1, 3].',
         'Adding 4 or 5 would go past 4. Skip those choices.',
         'Now start with 2. The smallest unused larger choice is 3. Even 2 + 3 is too large.',
         'Stop this path without trying 2 with 4 or 5. Larger starting numbers also cannot work.'],
        'Can you use 2 and 2 in this example?',
        'No. The rule requires two different numbers from the list. Only [1, 3] works.',
        {'Constraint': 'a rule the answer must follow', 'Search': 'try choices to find an answer'}),
    'dynamic-programming': (
        'Save small answers and reuse them',
        'Dynamic programming means saving answers to smaller problems. '
        'Use those saved answers to solve a larger problem instead of repeating the work.',
        'You can climb 1 or 2 steps at a time. Count the ways to climb 3 steps.',
        ['There is 1 way to climb 1 step: [1].', 'There are 2 ways to climb 2 steps: [1, 1] and [2].',
         'To reach step 3, arrive from step 2 or step 1.', 'Add their counts: 2 + 1 = 3 ways.'],
        'How many ways reach step 4? Use the counts for steps 3 and 2.',
        '3 + 2 = 5 ways. Save this count so you can use it for step 5.',
        {'State': 'the smaller problem we are counting, such as a step number',
         'Dynamic programming': 'solve small problems once and reuse their answers'}),
    'dp-grids': (
        'Build an answer one square at a time',
        'A grid is a table of squares. Some problems save a small answer in each square. '
        'A new square can use the answers just above it and beside it.',
        'A 2 by 2 grid has a start at top left and a finish at bottom right. Move only right or down.',
        ['There is 1 way to reach the top-right square: move right.',
         'There is 1 way to reach the bottom-left square: move down.',
         'The finish can be reached from either square. Add 1 + 1 = 2 ways.'],
        'List the two routes to the finish.',
        'Right then down, or down then right. Both end at the bottom-right square.',
        {'Grid': 'a table with rows and columns', 'Saved answer': 'a result kept so later squares can use it'}),
    'greedy': (
        'Make a useful choice now',
        'A greedy method makes one choice at a time and keeps it. It does not try every future plan. '
        'You must check why the rule works for your problem.',
        'You can carry 2 items. Their values are 5, 2, and 8. Each item takes one space.',
        ['Choose 8, the largest value.', 'One space remains. Choose 5, the next largest.',
         'The total is 13. Replacing either item with 2 would lower it.'],
        'What if you can carry only 1 item?',
        'Choose 8. This simple rule depends on every item taking one space. Different item sizes need more thought.',
        {'Greedy': 'choose the best current option and keep that choice', 'Limit': 'a rule such as how much you can carry'}),
    'intervals': (
        'Find times that overlap',
        'An interval has a start and an end. Meeting times are intervals. '
        'Two meetings overlap if they use some of the same time.',
        'Meeting A runs from 1 to 3. Meeting B runs from 2 to 4.',
        ['A starts first, at 1.', 'B starts at 2, before A ends at 3. They overlap.',
         'Together they cover the time from 1 to 4.'],
        'A meeting runs from 1 to 2. Another runs from 3 to 4. Do they overlap?',
        'No. The first ends before the second starts. Keep the two intervals separate.',
        {'Interval': 'a range with a start and an end', 'Overlap': 'share part of the same range', 'Merge': 'join into one range'}),
    'bits': (
        'Work with zeros and ones',
        'A bit is one digit: 0 or 1. Computers use groups of bits to store numbers. '
        'The places, from right to left, are worth 1, 2, 4, 8, and so on.',
        'What number does `101` mean?',
        ['The rightmost 1 is worth 1.', 'The middle 0 adds no 2.', 'The leftmost 1 is worth 4.', 'Add 4 + 1 = 5.'],
        'What number does `110` mean?',
        '4 + 2 = 6. The last 0 adds no 1.',
        {'Bit': 'a single 0 or 1', 'Binary': 'a way to write numbers using only 0 and 1'}),
    'tries': (
        'Share the start of words',
        'A trie stores words along paths of letters. Words with the same start share part of a path. '
        'A mark says where a complete word ends.',
        'Store `cat` and `car`.',
        ['Start with a path for c, then a.', 'Add a t branch and mark cat as a word.',
         'Add an r branch after a and mark car as a word.', 'Both words share the path c → a.'],
        'Is `ca` a complete saved word? Can it still be the start of a word?',
        'ca is not marked as a complete word. It is still the start of both cat and car.',
        {'Trie': 'a tree of letter paths used to store words', 'Prefix': 'the start of a word'}),
}


def lesson(identifier):
    """Return Markdown for learning and for a separate, fully worked example."""
    title, idea, example, steps, task, answer, words = _TOPICS[identifier]
    concept = '\n\n'.join([
        '## ' + title, '### Words you need',
        '\n'.join(f'- **{word}:** {meaning}' for word, meaning in words.items()),
        '### The idea', idea,
        'Start with the small example. Use paper if you want. You can write code after the steps make sense.',
    ])
    worked = '\n\n'.join([
        '### A small example', example,
        '\n'.join(f'{i}. {step}' for i, step in enumerate(steps, 1)),
        '### Your turn', task, '### Check your answer', answer,
    ])
    return {'title': title, 'concept': concept, 'worked_example': worked}
