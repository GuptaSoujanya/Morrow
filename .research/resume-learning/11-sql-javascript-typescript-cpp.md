# SQL, JavaScript, TypeScript, and C++

## What it is

This file covers the four general-purpose languages on the resume's skills list beyond Python: **SQL** (for MySQL/SQLite, listed under Data & Infra), **JavaScript**, **TypeScript**, and **C++**. Unlike the other topic files, these aren't tied to one specific resume bullet each - they're foundational languages that show up across the Next.js/React front-end work, the RideMate MERN backend, and general engineering fundamentals a CS degree and interview process expect regardless of which language a specific project used.

## How you used it

The resume's Languages line lists **Python, JavaScript, TypeScript, C++, SQL**, and the Data & Infra line lists **MongoDB, MySQL, SQLite** among the data stores. JavaScript and TypeScript are the direct implementation languages behind the Next.js/React dashboards, the Kuberha AI website, and the RideMate Node.js/Express/Socket.IO backend described elsewhere. SQL (MySQL/SQLite) represents relational-database work that sits alongside the MongoDB/Redis NoSQL stack used for RideMate - likely used for other internal tools, the Odoo labeling app's underlying database (Odoo is built on PostgreSQL, but the skill of writing SQL transfers directly), or structured reporting over evaluation/benchmark data. C++ is listed as a language skill, consistent with a CS degree's systems-programming coursework and foundational algorithmic interview preparation, even where it isn't tied to a specific production project bullet.

## Core concepts

**1. TypeScript as JavaScript plus a type system.** TypeScript compiles to JavaScript but adds static types checked at build time, catching a large class of bugs (wrong argument type, accessing a property that doesn't exist, forgetting to handle `null`) before code ever runs - directly relevant to the React/Next.js codebases described elsewhere, where component props and API response shapes benefit heavily from being typed.

```ts
interface TrainingMetric {
  step: number;
  loss: number;
  timestamp: string;
}

function formatMetric(m: TrainingMetric): string {
  return `step ${m.step}: loss=${m.loss.toFixed(4)}`;
}

// formatMetric({ step: 1, loss: "oops" }); // compile error: string not assignable to number
```

**2. JavaScript's async model.** Promises and `async`/`await` are the mechanism behind both the Node.js backend (database calls, Redis calls) and the React front-end (data fetching) described elsewhere; understanding the event loop - that JavaScript is single-threaded but non-blocking I/O lets many operations overlap - explains both why Node.js clustering (covered in the Node/Express file) is necessary for CPU-bound scaling, and why a single Node process can still handle many concurrent I/O-bound requests efficiently without clustering.

```js
async function getRideWithDriver(rideId) {
  const [ride, driver] = await Promise.all([
    Ride.findById(rideId),
    Driver.findById(ride.driverId), // bug: references `ride` before it's resolved in this shape
  ]);
  return { ride, driver };
}
```

(That snippet is a deliberately broken example worth recognizing in an interview: `Promise.all` evaluates both promises' *expressions* concurrently, so `ride.driverId` would be read before `ride` resolves - the fix is to await `ride` first, then fetch the driver.)

**3. SQL fundamentals: joins, indexes, and normalization.** Even in a primarily MongoDB/Node stack, SQL skill matters for any relational reporting or admin-tool work (and for interviews, which lean heavily on SQL regardless of what a candidate's day-to-day stack is). The core interview-relevant concepts: normalization (splitting data to avoid redundancy, e.g., separate `users` and `rides` tables rather than duplicating user info on every ride row), joins (combining rows across tables on a matching key), and indexes (speeding up lookups on frequently filtered/joined columns at the cost of slower writes and extra storage).

```sql
SELECT u.name, COUNT(r.id) AS ride_count
FROM users u
JOIN rides r ON r.user_id = u.id
WHERE r.created_at >= '2026-01-01'
GROUP BY u.id, u.name
HAVING COUNT(r.id) > 5
ORDER BY ride_count DESC;
```

```sql
CREATE INDEX idx_rides_user_created ON rides (user_id, created_at);
```

**4. SQLite versus MySQL as relational choices.** SQLite is a serverless, single-file database well-suited to local tooling, small internal apps, or embedded use (no separate database server process to run), while MySQL is a full client-server relational database meant for concurrent multi-user production workloads. Listing both suggests comfort choosing the right-sized tool - SQLite for something like a local eval-harness scratch database or a small internal tool, MySQL for a production multi-user system.

**5. C++ fundamentals relevant to interviews.** Even without a specific production C++ bullet on the resume, interview-relevant C++ knowledge centers on manual memory management (`new`/`delete`, and why modern C++ prefers RAII and smart pointers to avoid leaks), the distinction between stack and heap allocation, pass-by-value vs. pass-by-reference vs. pass-by-pointer, and how these affect performance and correctness in ways that garbage-collected languages like Python/JavaScript abstract away.

```cpp
#include <memory>
#include <vector>

class Node {
public:
    int value;
    std::unique_ptr<Node> next; // ownership is explicit; freed automatically
    Node(int v) : value(v), next(nullptr) {}
};

void appendToFront(std::unique_ptr<Node>& head, int v) {
    auto newNode = std::make_unique<Node>(v);
    newNode->next = std::move(head);
    head = std::move(newNode);
}
```

**6. Why this kind of cross-language fluency matters in practice.** The evaluation harness work (Python/FastAPI), the dashboard work (TypeScript/React), and the RideMate backend (JavaScript/Node) all required picking the right language for the job's ecosystem rather than forcing one language everywhere - FastAPI's typing/async story is a strong fit for the mock-service fleet, while TypeScript's type system is a strong fit for a large, multi-contributor dashboard codebase where catching prop-shape mistakes at compile time saves real debugging time.

**7. Common interview framing: comparing paradigms.** Interviewers often ask candidates to contrast languages directly - e.g., "why would you choose TypeScript over plain JavaScript for a large team project" (type safety, better IDE autocompletion, safer refactors) or "what does SQL give you that a document store like MongoDB doesn't" (strong relational integrity via foreign keys and transactions across normalized tables, versus MongoDB's flexibility for nested/variable-shape documents at the cost of weaker built-in referential integrity).

**8. SQL transactions and ACID basics.** A relational database transaction groups multiple statements so they either all succeed or all roll back together (atomicity), a property MongoDB historically lacked across multiple documents until multi-document transactions were added - worth knowing as a concrete tradeoff when explaining why a project chose SQL for one piece and MongoDB for another.

```sql
BEGIN;
UPDATE accounts SET balance = balance - 100 WHERE id = 1;
UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT; -- both updates succeed together, or neither does if an error occurs before COMMIT
```

## Interview questions and answers

**Q1: Why would you choose TypeScript over plain JavaScript for a dashboard codebase with multiple contributors?**
TypeScript catches a large class of bugs - wrong prop types, missing null checks, mismatched API response shapes - at compile time rather than at runtime, and it gives better IDE autocompletion and safer refactoring, which matters more as a codebase and team grow. The cost is some upfront type-authoring overhead, which is worth it once a codebase is large enough that runtime type bugs become a recurring source of production issues.

**Q2: Explain the difference between `Promise.all` and sequential `await` calls, and when you'd choose each.**
`Promise.all` starts all the given promises concurrently and waits for all to resolve, which is faster when the operations are independent; sequential `await` calls run one after another, which is necessary when a later call depends on an earlier call's result (as in the deliberately-broken example above, where you must await the ride before you can use its `driverId`).

**Q3: When would you choose SQL/MySQL over a document store like MongoDB for a given piece of data?**
When the data has strong relational structure that benefits from enforced referential integrity (foreign keys) and multi-table transactions - financial records, user-role/permission tables, anything where "these two rows must update together or not at all" matters a lot. MongoDB is a better fit when the data's shape varies across records or nests naturally (a document per ride with embedded driver/rider snapshots) and you don't need cross-document transactional guarantees as a primary concern.

**Q4: What's the difference between a clustered and non-clustered index conceptually, and why do indexes speed up queries?**
An index is a separate, ordered data structure (commonly a B-tree) that lets the database jump directly to matching rows instead of scanning the whole table; a clustered index determines the physical storage order of the table's rows (so a table can have at most one), while non-clustered indexes are separate structures pointing back to the row's location, and a table can have several.

**Q5: Why does C++ require manual attention to memory ownership that Python/JavaScript don't?**
Python and JavaScript use garbage collection to automatically reclaim memory no longer reachable; C++ (without smart pointers) requires the programmer to explicitly `delete` what was `new`-ed, and forgetting to do so leaks memory, while deleting twice or using a dangling pointer after deletion causes undefined behavior - smart pointers (`unique_ptr`, `shared_ptr`) exist specifically to make ownership explicit and automate the deletion.

**Q6: What's a `JOIN` doing under the hood, and what's the difference between `INNER JOIN` and `LEFT JOIN`?**
A join combines rows from two tables where a specified condition (usually matching a foreign key to a primary key) holds. `INNER JOIN` only returns rows that have a match in both tables; `LEFT JOIN` returns every row from the left table regardless of whether a match exists in the right table, filling in NULLs for the right table's columns when there's no match - useful for "show all users, with their ride count if any, including users with zero rides."

**Q7: What problem do database transactions solve, and give an example where skipping them would cause a real bug.**
Transactions guarantee a group of statements either all commit or all roll back together, preventing partial updates from being visible. A classic example: transferring money between two accounts as two separate `UPDATE` statements without a transaction - if the process crashes between the debit and the credit, money has vanished from the system; wrapping both in a transaction prevents that half-completed state from ever being persisted.

**Q8: How would you decide between SQLite and MySQL for a new internal tool?**
SQLite for something single-user or low-concurrency that doesn't need a separate running database server - a local script's scratch storage, a small desktop/internal tool - since it's just a file and has zero operational overhead. MySQL once you need real concurrent multi-user access, network access from multiple services, or production-grade backup/replication tooling.

**Q9: What's a subtle JavaScript async bug you'd watch for in code review?**
Forgetting to `await` a promise inside a loop or a `.map()` call that's expected to run sequentially or whose errors need to propagate - e.g., `items.forEach(async (item) => await process(item))` looks sequential but actually fires all the async calls without waiting for any of them, since `forEach` doesn't await its callback's return value, silently swallowing ordering guarantees and unhandled rejections.

**Q10: If you had a pointer-heavy C++ data structure bug (say, a crash in a linked-list implementation), how would you approach debugging it?**
Check ownership first - who is responsible for deleting each node, and is any node being deleted more than once or accessed after deletion (a classic use-after-free) - using tools like AddressSanitizer or Valgrind to catch invalid memory access precisely, and consider whether switching raw pointers to `unique_ptr`/`shared_ptr` would make the ownership bug impossible to write in the first place rather than just easier to find.

## Hands-on

1. **Write a typed API client in TypeScript.** Define an interface for a JSON API response shape, write a `fetchMetrics(): Promise<TrainingMetric[]>` function with that return type, and intentionally introduce a type mismatch to observe the compiler catch it.
2. **Write and index a small SQL schema.** Create `users` and `rides` tables with a foreign key relationship, insert a handful of rows, write a `JOIN` query to find each user's ride count, then add an index on the join column and use `EXPLAIN` to see how the query plan changes.

## Read next

- [TypeScript handbook](https://www.typescriptlang.org/docs/handbook/intro.html)
- [MDN JavaScript async/await guide](https://developer.mozilla.org/en-US/docs/Learn/JavaScript/Asynchronous/Async_await)
- [MySQL documentation](https://dev.mysql.com/doc/)
- [cppreference (smart pointers)](https://en.cppreference.com/w/cpp/memory)
- [../../course/02-dsa/03-stack-queue-linkedlist.md](../../course/02-dsa/03-stack-queue-linkedlist.md)
- [../../course/01-system-design/02-storage-and-databases.md](../../course/01-system-design/02-storage-and-databases.md)
