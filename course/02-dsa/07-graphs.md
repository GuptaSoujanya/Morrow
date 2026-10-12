# Chapter 7: Graphs

## 1. Concept

A **graph** is a set of nodes (vertices) connected by edges. Edges can be **directed** (one-way, like a Twitter follow) or **undirected** (two-way, like a Facebook friendship), and **weighted** (edges have a cost) or **unweighted**.

```
Undirected, unweighted graph:          Directed graph (for topological sort):
                                               A -> B
   A --- B                                    |    |
   |     |                                     v    v
   C --- D --- E                               C -> D

Adjacency list representation (most common in interviews):
  graph = {
      "A": ["B", "C"],
      "B": ["A", "D"],
      "C": ["A", "D"],
      "D": ["B", "C", "E"],
      "E": ["D"],
  }
```

Trees (Chapter 5) are actually just a special kind of graph — one with no cycles and exactly one path between any two nodes. Everything you learned about DFS/BFS on trees applies here, with one addition: **graphs can have cycles, so you must track visited nodes** to avoid infinite loops.

## 2. When to Use This Pattern

- Input is described as nodes/edges, a grid (2D grid = graph where each cell is a node connected to its neighbors), a network, or relationships between items.
- "Shortest path in unweighted graph" → BFS.
- "Does a path exist / explore all connected regions" → DFS or BFS (either works for reachability).
- "Order tasks given dependencies" → Topological Sort (needs a Directed Acyclic Graph, DAG).
- "Are these two nodes connected? Group items into connected components" → Union-Find (Disjoint Set Union).
- "Shortest path with weighted edges" → Dijkstra's algorithm.
- "Connect all nodes with minimum total edge cost" → Minimum Spanning Tree (Prim's or Kruskal's).

## 3. Template / Skeleton Code

```python
from collections import deque, defaultdict
import heapq


def dfs_template(graph: dict, start, visited: set | None = None):
    if visited is None:
        visited = set()
    if start in visited:
        return
    visited.add(start)
    # process start here
    for neighbor in graph[start]:
        if neighbor not in visited:
            dfs_template(graph, neighbor, visited)


def bfs_template(graph: dict, start):
    visited = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        # process node here
        for neighbor in graph[node]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # path compression
        return self.parent[x]

    def union(self, a: int, b: int) -> bool:
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return False  # already connected
        if self.rank[root_a] < self.rank[root_b]:
            root_a, root_b = root_b, root_a
        self.parent[root_b] = root_a
        if self.rank[root_a] == self.rank[root_b]:
            self.rank[root_a] += 1
        return True
```

---

## 4. Problems (Basic → Advanced)

### Problem 1: Number of Islands
**Statement:** Given a 2D grid of `'1'` (land) and `'0'` (water), return the number of islands (connected groups of land, horizontally/vertically adjacent).

**Example:**
```
Input:
[["1","1","0","0"],
 ["1","1","0","0"],
 ["0","0","1","0"],
 ["0","0","0","1"]]
Output: 3
```

**Approach:** Scan every cell. Whenever you find unvisited land, it's a new island — increment the count, then DFS (or BFS) outward from it, marking every connected land cell as visited so we never count it again.

```python
def num_islands(grid: list[list[str]]) -> int:
    if not grid:
        return 0

    rows, cols = len(grid), len(grid[0])
    visited = set()

    def dfs(r: int, c: int) -> None:
        if (r < 0 or r >= rows or c < 0 or c >= cols
                or grid[r][c] == "0" or (r, c) in visited):
            return
        visited.add((r, c))
        dfs(r + 1, c)
        dfs(r - 1, c)
        dfs(r, c + 1)
        dfs(r, c - 1)

    islands = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == "1" and (r, c) not in visited:
                islands += 1
                dfs(r, c)

    return islands


if __name__ == "__main__":
    grid = [
        ["1", "1", "0", "0"],
        ["1", "1", "0", "0"],
        ["0", "0", "1", "0"],
        ["0", "0", "0", "1"],
    ]
    print(num_islands(grid))  # 3
```

**Complexity:** Time O(rows × cols), Space O(rows × cols) for `visited` and the recursion stack.

---

### Problem 2: Clone Graph
**Statement:** Given a reference to a node in a connected undirected graph, return a deep copy (clone) of the entire graph.

**Example:**
```
Input: adjList = [[2,4],[1,3],[2,4],[1,3]]
Output: a new graph with the same structure, but entirely new node objects
```

**Approach:** DFS the original graph, and for every original node, create a matching clone. Use a hash map from original node → clone node, both to avoid infinite loops (cycles) and to avoid creating duplicate clones for the same node.

```python
class Node:
    def __init__(self, val=0, neighbors=None):
        self.val = val
        self.neighbors = neighbors if neighbors is not None else []


def clone_graph(node: Node | None) -> Node | None:
    if node is None:
        return None

    old_to_new: dict[Node, Node] = {}

    def dfs(original: Node) -> Node:
        if original in old_to_new:
            return old_to_new[original]

        clone = Node(original.val)
        old_to_new[original] = clone

        for neighbor in original.neighbors:
            clone.neighbors.append(dfs(neighbor))

        return clone

    return dfs(node)


if __name__ == "__main__":
    n1, n2, n3, n4 = Node(1), Node(2), Node(3), Node(4)
    n1.neighbors = [n2, n4]
    n2.neighbors = [n1, n3]
    n3.neighbors = [n2, n4]
    n4.neighbors = [n1, n3]

    cloned = clone_graph(n1)
    print(cloned.val)                                  # 1
    print(sorted(n.val for n in cloned.neighbors))       # [2, 4]
    print(cloned is n1)                                  # False (it's a real clone)
```

**Complexity:** Time O(V + E) — visits every node and edge once. Space O(V) for the hash map.

---

### Problem 3: Course Schedule (Topological Sort / Cycle Detection)
**Statement:** There are `numCourses` courses labeled `0` to `numCourses - 1`. Given prerequisite pairs `[a, b]` meaning "to take course `a`, you must first take course `b`," determine if it's possible to finish all courses (i.e., is there no cyclic dependency?).

**Example:**
```
Input: numCourses = 2, prerequisites = [[1, 0]]
Output: True   # take 0, then 1

Input: numCourses = 2, prerequisites = [[1, 0], [0, 1]]
Output: False  # 0 needs 1, and 1 needs 0 -> impossible cycle
```

**Approach:** This is cycle detection in a directed graph, solved with **Kahn's algorithm** (BFS-based topological sort): compute each course's in-degree (number of prerequisites). Start a queue with all courses that have zero prerequisites. Process the queue, "removing" each course and decrementing the in-degree of courses that depend on it; whenever a course's in-degree hits zero, add it to the queue. If we can process all courses this way, there's no cycle.

```python
from collections import deque, defaultdict

def can_finish(num_courses: int, prerequisites: list[list[int]]) -> bool:
    graph = defaultdict(list)   # prereq -> list of courses that need it
    in_degree = [0] * num_courses

    for course, prereq in prerequisites:
        graph[prereq].append(course)
        in_degree[course] += 1

    queue = deque(c for c in range(num_courses) if in_degree[c] == 0)
    completed = 0

    while queue:
        course = queue.popleft()
        completed += 1
        for next_course in graph[course]:
            in_degree[next_course] -= 1
            if in_degree[next_course] == 0:
                queue.append(next_course)

    return completed == num_courses


if __name__ == "__main__":
    print(can_finish(2, [[1, 0]]))          # True
    print(can_finish(2, [[1, 0], [0, 1]]))  # False
    print(can_finish(4, [[1, 0], [2, 0], [3, 1], [3, 2]]))  # True
```

**Complexity:** Time O(V + E), Space O(V + E).

---

### Problem 4: Number of Connected Components (Union-Find)
**Statement:** Given `n` nodes labeled `0` to `n-1` and a list of undirected edges, return the number of connected components.

**Example:**
```
Input: n = 5, edges = [[0,1],[1,2],[3,4]]
Output: 2   # {0,1,2} and {3,4}
```

**Approach:** Start with `n` separate components. For each edge, union its two nodes. Each successful union (joining two previously-separate groups) reduces the component count by one. Union-Find with path compression and union by rank makes each operation nearly O(1).

```python
class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n
        self.count = n  # number of components

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return
        if self.rank[root_a] < self.rank[root_b]:
            root_a, root_b = root_b, root_a
        self.parent[root_b] = root_a
        if self.rank[root_a] == self.rank[root_b]:
            self.rank[root_a] += 1
        self.count -= 1


def count_components(n: int, edges: list[list[int]]) -> int:
    uf = UnionFind(n)
    for a, b in edges:
        uf.union(a, b)
    return uf.count


if __name__ == "__main__":
    print(count_components(5, [[0, 1], [1, 2], [3, 4]]))  # 2
    print(count_components(5, [[0, 1], [1, 2], [2, 3], [3, 4]]))  # 1
```

**Complexity:** Time O(E · α(V)) where α is the (effectively constant) inverse Ackermann function — practically O(E). Space O(V).

---

### Problem 5: Pacific Atlantic Water Flow (Multi-source BFS/DFS)
**Statement:** Given an `m x n` grid of heights, water can flow from a cell to an adjacent cell with height ≤ its own. Find all cells from which water can flow to BOTH the Pacific (top/left edges) and Atlantic (bottom/right edges) oceans.

**Example:**
```
Input: heights = [[1,2,2,3,5],
                   [3,2,3,4,4],
                   [2,4,5,3,1],
                   [6,7,1,4,5],
                   [5,1,1,2,4]]
Output: [[0,4],[1,3],[1,4],[2,2],[3,0],[3,1],[4,0]]
```

**Approach:** Instead of checking "can this cell reach the ocean?" for every cell individually (which is slow, since water flows "downhill" but we'd be checking "uphill" reachability), reverse the problem: start DFS/BFS *from* every ocean-border cell, flowing "uphill" (to neighbors with height ≥ current). Mark all cells reachable from the Pacific borders, and separately all cells reachable from the Atlantic borders. The answer is the intersection.

```python
def pacific_atlantic(heights: list[list[int]]) -> list[list[int]]:
    if not heights:
        return []

    rows, cols = len(heights), len(heights[0])
    pacific_reachable = set()
    atlantic_reachable = set()

    def dfs(r: int, c: int, visited: set, prev_height: int) -> None:
        if (r < 0 or r >= rows or c < 0 or c >= cols
                or (r, c) in visited or heights[r][c] < prev_height):
            return
        visited.add((r, c))
        dfs(r + 1, c, visited, heights[r][c])
        dfs(r - 1, c, visited, heights[r][c])
        dfs(r, c + 1, visited, heights[r][c])
        dfs(r, c - 1, visited, heights[r][c])

    for c in range(cols):
        dfs(0, c, pacific_reachable, heights[0][c])          # top row -> Pacific
        dfs(rows - 1, c, atlantic_reachable, heights[rows - 1][c])  # bottom row -> Atlantic

    for r in range(rows):
        dfs(r, 0, pacific_reachable, heights[r][0])           # left col -> Pacific
        dfs(r, cols - 1, atlantic_reachable, heights[r][cols - 1])  # right col -> Atlantic

    return [[r, c] for r in range(rows) for c in range(cols)
            if (r, c) in pacific_reachable and (r, c) in atlantic_reachable]


if __name__ == "__main__":
    heights = [
        [1, 2, 2, 3, 5],
        [3, 2, 3, 4, 4],
        [2, 4, 5, 3, 1],
        [6, 7, 1, 4, 5],
        [5, 1, 1, 2, 4],
    ]
    result = pacific_atlantic(heights)
    print(sorted(result))
```

**Complexity:** Time O(rows × cols), Space O(rows × cols).

---

### Problem 6: Network Delay Time (Dijkstra's Algorithm)
**Statement:** `n` network nodes labeled `1` to `n`. Given directed, weighted edges `times = [[u, v, w], ...]` (signal from `u` to `v` takes `w` time), and a starting node `k`, return the time for all nodes to receive the signal, or `-1` if impossible.

**Example:**
```
Input: times = [[2,1,1],[2,3,1],[3,4,1]], n = 4, k = 2
Output: 2
```

**Approach:** This is shortest path from a single source in a weighted graph — Dijkstra's algorithm. Use a min-heap keyed by distance. Always expand the closest known unvisited node next, relaxing (potentially improving) the distance to its neighbors. The answer is the maximum distance across all nodes (the last node to receive the signal), or -1 if any node is unreachable.

```python
import heapq
from collections import defaultdict

def network_delay_time(times: list[list[int]], n: int, k: int) -> int:
    graph = defaultdict(list)
    for u, v, w in times:
        graph[u].append((v, w))

    min_heap = [(0, k)]  # (distance, node)
    visited_distance: dict[int, int] = {}

    while min_heap:
        dist, node = heapq.heappop(min_heap)
        if node in visited_distance:
            continue
        visited_distance[node] = dist

        for neighbor, weight in graph[node]:
            if neighbor not in visited_distance:
                heapq.heappush(min_heap, (dist + weight, neighbor))

    if len(visited_distance) != n:
        return -1
    return max(visited_distance.values())


if __name__ == "__main__":
    print(network_delay_time([[2, 1, 1], [2, 3, 1], [3, 4, 1]], 4, 2))  # 2
    print(network_delay_time([[1, 2, 1]], 2, 1))                         # 1
    print(network_delay_time([[1, 2, 1]], 2, 2))                         # -1
```

**Complexity:** Time O(E log V) with a binary heap, Space O(V + E).

---

### Problem 7: Minimum Spanning Tree — Connecting Cities with Minimum Cost (Kruskal's Algorithm)
**Statement:** Given `n` cities and a list of `connections = [[city1, city2, cost], ...]`, find the minimum total cost to connect all cities so that every city can reach every other city (directly or indirectly). Return `-1` if it's impossible.

**Example:**
```
Input: n = 3, connections = [[1,2,5],[1,3,6],[2,3,1]]
Output: 6   # Use edges (2,3,1) and (1,2,5) -> total 1 + 5 = 6
```

**Approach:** Kruskal's algorithm: sort all edges by cost, ascending. Greedily add each edge if it connects two previously-separate components (checked/merged with Union-Find). Skip edges that would create a cycle (connecting two nodes already in the same component — wasteful). Stop once all nodes are connected (n-1 edges added) or edges run out.

```python
class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n + 1))  # 1-indexed cities

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: int, b: int) -> bool:
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return False
        self.parent[root_b] = root_a
        return True


def min_cost_connect_points(n: int, connections: list[list[int]]) -> int:
    connections.sort(key=lambda edge: edge[2])  # sort by cost
    uf = UnionFind(n)

    total_cost = 0
    edges_used = 0

    for city1, city2, cost in connections:
        if uf.union(city1, city2):
            total_cost += cost
            edges_used += 1
            if edges_used == n - 1:
                break

    return total_cost if edges_used == n - 1 else -1


if __name__ == "__main__":
    print(min_cost_connect_points(3, [[1, 2, 5], [1, 3, 6], [2, 3, 1]]))  # 6
    print(min_cost_connect_points(4, [[1, 2, 3], [3, 4, 4]]))              # -1 (disconnected)
    print(min_cost_connect_points(1, []))                                   # 0 (single city, no edges needed)
```

**Complexity:** Time O(E log E) for sorting edges, Space O(V + E).

---

## 5. Complexity Summary

| Problem | Time | Space |
|---------|------|-------|
| Number of Islands | O(rows × cols) | O(rows × cols) |
| Clone Graph | O(V + E) | O(V) |
| Course Schedule | O(V + E) | O(V + E) |
| Number of Connected Components | O(E · α(V)) ≈ O(E) | O(V) |
| Pacific Atlantic Water Flow | O(rows × cols) | O(rows × cols) |
| Network Delay Time (Dijkstra) | O(E log V) | O(V + E) |
| Connecting Cities (Kruskal's MST) | O(E log E) | O(V + E) |

---

## 6. Interview Tips

- **Always ask: directed or undirected? Weighted or unweighted? Can there be cycles?** These three questions determine which algorithm applies, and asking them signals real understanding, not memorized code.
- **Name the algorithm you're using, immediately.** Say "I'll use Kahn's algorithm for topological sort" or "This is Dijkstra's algorithm since edges are weighted and non-negative" before writing code. It tells the interviewer you recognize the pattern rather than improvising.
- **Mention why Dijkstra needs non-negative weights.** If asked a follow-up ("what if weights can be negative?"), say you'd need Bellman-Ford instead, since Dijkstra's greedy "closest first" assumption breaks with negative edges.
- **For grid problems, explicitly state you're treating the grid as a graph.** Say: "Each cell is a node, and it's connected to up to 4 neighbors (up/down/left/right)" — this reframing makes it obvious that standard BFS/DFS applies.
- **Union-Find vs. BFS/DFS for connectivity — know when each shines.** BFS/DFS is natural for a single static query ("is the graph connected?"). Union-Find shines when edges are added incrementally and you need to repeatedly answer "are these two nodes connected now?" efficiently (e.g., Kruskal's MST, or "redundant connection" problems).
- **For MST, mention the alternative (Prim's) even if you code Kruskal's.** Say: "Kruskal's sorts edges and uses Union-Find; Prim's instead grows the tree from a start node using a min-heap of available edges — both give the correct minimum total cost, I'm picking Kruskal's because it's simpler to code with Union-Find already in mind."
