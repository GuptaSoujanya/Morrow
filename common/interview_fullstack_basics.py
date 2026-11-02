"""Small, plain-English full-stack lessons for the shared 90-day course.

Each numbered lesson follows the corresponding full-stack topic in
``interview_course.day_spec``. The examples are authored teaching material;
this module does not read files, call services, or access learner data.
"""
from __future__ import annotations

from copy import deepcopy


def _item(title, idea, example, steps, task, answer, words):
    return dict(title=title, idea=idea, example=example, steps=steps,
                task=task, answer=answer, words=words)


_LESSONS = {
    1: _item(
        'Give a program a value and get an answer',
        'Python is a language for giving computers instructions. A value is one piece of information, such as 20. A function is a named set of instructions you can use again. An API lets another program ask your program to do something.',
        'Try this Python code:\n\n```python\ndef add_five(minutes):\n    return minutes + 5\nprint(add_five(20))\n```\n\n'
        'Line 1 names a function and its input, minutes. Line 2 adds 5 and returns the answer; '
        'its starting spaces put it inside the function. Line 3 calls the function with 20 and prints 25. '
        'An API could call this function for a page.',
        ['Start with 20 study minutes.', 'Add 5 minutes.', 'Write the answer that the function sends back.'],
        'Use the same add_five function with 10 minutes.',
        'It returns 15 because 10 + 5 = 15. The input changed; the instruction did not.',
        {'input': 'Information given to a program.', 'return': 'Send an answer back from a function.',
         'variable': 'A name that refers to a value.', 'API': 'An agreed way for programs to ask each other for information or work.'}),
    2: _item(
        'Make a page people can read and use',
        'HTML describes what is on a web page, such as a heading or button. CSS controls how those things look. An accessible page lets people use it with a keyboard or a tool that reads text aloud.',
        'A study page has a heading saying Today, a box labelled Study minutes, and a Save button. '
        'HTML supplies these parts. CSS makes the words dark on a light background. '
        'Pressing the Tab key reaches the box and then the button, with a visible outline around the selected part.',
        ['Write a clear label for the minutes box.', 'Choose readable text and background colours.',
         'Move through the page using only the Tab key.'],
        'Replace a button labelled Go with words that explain what it does.',
        'Save study minutes tells the learner what will happen before they press it.',
        {'HTML': 'The language that describes the parts of a web page.', 'CSS': 'Rules for how a page looks.',
         'label': 'Text that names a box or control.', 'keyboard focus': 'The part of a page that currently receives keyboard input.'}),
    3: _item(
        'Make a button change a number',
        'JavaScript is a language that can make a web page respond to people. A variable holds a value the program needs. An event tells the program that something happened, such as a button being pressed.',
        'Try this JavaScript in a browser console:\n\n```javascript\nlet minutes = 0;\nminutes = minutes + 5;\nconsole.log(minutes);\n```\n\n'
        'Line 1 names a variable and starts it at 0. Line 2 adds 5 to its current value. '
        'Line 3 displays 5 in the console, the browser’s place for trying code. '
        'A button’s click event can run the same add-5 step again and update the visible page.',
        ['Start the counter at 0.', 'On each button press, add 5 to the current number.',
         'Show the updated number on the page.'],
        'What should the page show after three presses?',
        '15 minutes: 0 becomes 5, then 10, then 15. Starting from 0 on every press would be a mistake.',
        {'JavaScript': 'A programming language often used in web pages.', 'variable': 'A name for a value.',
         'event': 'A signal that something happened.', 'function': 'A named set of instructions.'}),
    4: _item(
        'Send the study minutes in a shared format',
        'A page and a server need to agree on how information is written. JSON is a text format they can both read. It pairs names with values, so each number has a clear meaning.',
        'The page sends {"minutes": 20}. Here minutes is the name and 20 is its value. '
        'The server reads it, saves the study time, and replies {"saved": true}. '
        'The word true means yes. A successful save message appears only after that reply arrives.',
        ['Choose minutes as the name of the number.', 'Send the number as JSON.',
         'Read the reply before showing Saved.'],
        'Write the JSON for a study session lasting 30 minutes.',
        '{"minutes": 30}. The number has no quotation marks because it is a number, not a piece of text.',
        {'JSON': 'A text format for sharing values between programs.', 'server': 'A program that receives and answers requests.',
         'request': 'A message asking a program to do something.', 'response': 'The message sent back.'}),
    5: _item(
        'Keep study sessions in a table',
        'A database keeps information after the page closes. A table arranges that information in rows and columns, like a simple sheet. SQL is a language for asking a database to read or change rows.',
        'A sessions table has columns id and minutes. Its rows are (1, 20) and (2, 30). '
        'Run this SQL after creating those rows:\n\n```sql\nSELECT minutes FROM sessions;\n```\n\n'
        'This one line asks for the minutes column from the sessions table. '
        'The result contains 20 and 30; adding them gives 50 study minutes.',
        ['Draw columns named id and minutes.', 'Put each session in its own row.',
         'Give each row a different id.'],
        'Add a third session lasting 10 minutes. What is the new total?',
        'Use a new id, such as 3. The minutes are 20, 30 and 10, so the total is 60.',
        {'database': 'A place where a program stores organised information.', 'row': 'One saved record.',
         'column': 'One kind of information in every row.', 'key': 'A value used to identify a row.'}),
    6: _item(
        'Connect the page to saved information',
        'The page collects what the person types. The server checks it and asks the database to save it. The page then shows the result returned by the server.',
        'You type 20 and press Save. The page sends 20 to the server. '
        'The server checks that it is a positive number, saves a session with id 7, and replies with that saved session. '
        'The page adds session 7 to the list. Reloading the page asks the server for the saved list again.',
        ['Follow the number from the input box to the server.', 'Check and save it in the database.',
         'Show the saved result on the page.'],
        'Where should the final check for negative minutes happen?',
        'On the server. A page can help catch mistakes, but someone can send a request without using that page.',
        {'frontend': 'The part of an app that a person sees and uses.', 'backend': 'The server work behind the page.',
         'validation': 'Checking that information follows the required rules.'}),
    7: _item(
        'Build one complete study-tracker action',
        'A useful small project completes one action from start to finish. Your study tracker should save minutes and show the saved total. Explaining each part helps you notice missing steps.',
        'The saved list starts with 20 minutes. You add 10, see a total of 30, and reload the page. '
        'It should still show 30 because the database kept both sessions. '
        'If it returns to 20, the page may have changed its display without saving the new session.',
        ['Save a 10-minute session.', 'Check that the displayed total increases by 10.',
         'Reload and check the total again.'],
        'Draw the journey of a saved session using four boxes.',
        'Input box → server check → database save → page result. On reload, the server reads the database again.',
        {'end to end': 'Following an action through every part needed to finish it.',
         'reload': 'Ask the browser to load the page again.', 'persistence': 'Keeping information after the current program or page closes.'}),
    8: _item(
        'Collect values and check them before saving',
        'Python can keep several values in a list. A dictionary pairs names with values, such as minutes with 20. Check incoming values before using them in a calculation or saving them.',
        'An imported list contains 20, -5 and 30 study minutes. The rule says each value must be a whole number above 0. '
        '20 and 30 pass; -5 fails. If the import permits saving valid entries separately, the saved total is 50 and the rejected entry is reported.',
        ['Read each value in the list.', 'Check whether it is a positive whole number.',
         'Keep valid values and describe any rejected ones.'],
        'Check the values 15, "hello" and 0 using the same rule.',
        'Only 15 passes. "hello" is text and 0 is not above 0. Tell the user which entries need fixing.',
        {'list': 'An ordered collection of values.', 'dictionary': 'A collection that pairs names with values.',
         'validation': 'Checking values against rules.', 'whole number': 'A number without a fraction, such as 15.'}),
    9: _item(
        'Match tables and count related records',
        'Different tables can store different kinds of information. A join matches related rows using a shared value. Grouping then lets us calculate one result for each person or category.',
        'The learners table says id 1 is Asha and id 2 is Ravi. '
        'The sessions table has (learner 1, 20 minutes), (learner 1, 10 minutes), and (learner 2, 15 minutes). '
        'Matching the learner id gives names to sessions. Grouping by learner gives Asha 30 minutes and Ravi 15.',
        ['Find the learner id in each session.', 'Match that id to the learners table.',
         'Add minutes separately for each learner.'],
        'Asha studies another 5 minutes. What should the grouped report show?',
        'Asha: 35 minutes. Ravi: 15 minutes. The new session changes only Asha’s group.',
        {'join': 'Match related rows from different tables.', 'group': 'Put rows with the same chosen value together.',
         'sum': 'The result of adding numbers.', 'learner id': 'A saved value that identifies one learner.'}),
    10: _item(
        'Help the database find the right rows',
        'A database can search every row to find one learner’s sessions. An index keeps a lookup structure that can make that search faster. Keeping the index up to date also costs work when rows change.',
        'Imagine 10,000 session rows and a request for learner 7. Without a useful lookup, the database may inspect all 10,000. '
        'An index on learner_id helps it locate matching rows. '
        'A query plan describes the search the database expects to use; it does not guarantee every request is fast.',
        ['Identify the column used to find rows.', 'Consider an index on that column.',
         'Compare the database’s search plan before and after.'],
        'Which column would you first consider indexing for requests that find sessions by learner?',
        'learner_id, because that is the value used to locate matching sessions. Measure the result before adding more indexes.',
        {'index': 'A lookup structure that helps find rows.', 'query': 'A request for information from a database.',
         'query plan': 'The steps a database expects to use to answer a query.'}),
    11: _item(
        'Save related changes together',
        'Some changes must succeed together to keep information correct. A transaction treats those changes as one unit. A migration is a recorded change to the shape of the database, such as adding a column.',
        'Moving 10 study points from one account to another needs two updates: subtract 10 and add 10. '
        'If the second update fails, a transaction can undo the first so no points disappear. '
        'Separately, adding a notes column to sessions is a migration; existing rows need an allowed starting value.',
        ['List the changes that must happen together.', 'Put them in one database transaction.',
         'Test what happens when the second change fails.'],
        'Two accounts start with 30 and 20 points. A transfer fails halfway. What should remain?',
        '30 and 20. The failed transaction must leave neither account partly changed.',
        {'transaction': 'Database changes that succeed together or are undone together.',
         'migration': 'A recorded change to database structure.', 'rollback': 'Undo changes that should not be kept.'}),
    12: _item(
        'Tell people when a request is waiting or fails',
        'A page needs more than a successful result. While a request is running, show that the app is working. If it fails, explain what the person can do next without claiming the work succeeded.',
        'After Save is pressed, the button says Saving. A reply with status 400 and a message about negative minutes changes the page to Enter minutes above 0. '
        'A network failure instead shows Could not confirm the save. The page keeps the entered value so the person does not need to type it again.',
        ['Show a waiting message as the request starts.', 'Use the reply to choose success or error.',
         'Keep the person’s input when an error happens.'],
        'What message should appear when the server rejects minutes of -3?',
        'Enter minutes above 0. This explains the fix; a general Something went wrong message would not.',
        {'HTTP status': 'A number describing the result of a web request.', 'loading state': 'The page while it waits for work.',
         'network': 'The connection used to send messages between computers.'}),
    13: _item(
        'Check a small function and a complete request',
        'A test runs an action and checks its result. A unit test checks a small piece, such as a total function. An integration test checks that connected parts, such as an API and a test database, work together.',
        'A unit test gives the total function [20, 10] and expects 30. '
        'An API test sends a 10-minute session to a separate test database, then requests the list and checks that the session is there. '
        'A second API test sends -5 and checks that it is rejected without creating a row.',
        ['Write the expected answer before running the test.', 'Test one valid input.',
         'Test an invalid input and check that nothing was saved.'],
        'What should the total function return for an empty list?',
        '0, because there are no minutes to add. This checks a boundary case that ordinary examples can miss.',
        {'unit test': 'A check of a small piece of code.', 'integration test': 'A check of connected pieces working together.',
         'expected result': 'The answer the test should receive.', 'boundary case': 'An input near an edge, such as an empty list.'}),
    14: _item(
        'Build a dashboard you can check',
        'A dashboard shows useful summaries of saved information. Its numbers must follow clear rules. Testing those rules with a tiny known dataset makes mistakes easier to find.',
        'The test database has Asha’s sessions of 20 and 10 minutes and Ravi’s session of 15. '
        'The dashboard should show a total of 45, three sessions, and Asha’s total of 30. '
        'If a learner filter selects Ravi, the visible total should become 15 and the session count should become one.',
        ['Start with three known session records.', 'Calculate the expected totals by hand.',
         'Compare the dashboard with those answers.'],
        'After selecting Asha, what total and session count should appear?',
        '30 minutes across two sessions. The count is the number of sessions, not the number of learners.',
        {'dashboard': 'A page that shows useful summaries.', 'filter': 'A rule that selects which records to show.',
         'dataset': 'A collection of records used together.'}),
    15: _item(
        'Build a page from small parts',
        'A component is a reusable piece of a page. Props are values passed into that piece. State is information the page remembers while a person uses it, such as which session is selected.',
        'A SessionCard component receives the label Reading and the number 20 as props. '
        'Another card receives Coding and 30. Both use the same layout. '
        'The page stores selectedSession as state; choosing the Coding card changes that state and the visible selection.',
        ['Choose one repeated page part.', 'List the values it needs from its parent page.',
         'Keep the changing selection in page state.'],
        'A card displays 15 minutes from its parent. Is 15 a prop or the page’s selection state?',
        'It is a prop passed to the card. The selected card is separate state that can change when the user chooses another card.',
        {'component': 'A reusable piece of a page.', 'prop': 'A value passed into a component.',
         'state': 'Information a page remembers and updates during use.', 'parent': 'The component that contains another component.'}),
    16: _item(
        'Make a form easy to complete correctly',
        'A form collects related answers from a person. Clear labels explain what to enter. Check values on the page for quick help and check them again on the server before saving.',
        'A session form asks for a title and minutes. The title is Reading and minutes is blank. '
        'Instead of clearing the form, the page shows Enter study minutes beside that box. '
        'After the person enters 20, the server repeats the checks and saves the valid session.',
        ['Give every input a visible label.', 'Show a specific message beside an invalid input.',
         'Keep valid answers when another answer needs fixing.'],
        'Write an error message for a title containing only spaces.',
        'Enter a session title. Spaces alone do not name the session; remove outer spaces before checking whether text remains.',
        {'form': 'A group of input boxes used for one task.', 'input': 'A place where a person enters information.',
         'validation': 'Checking that answers follow the required rules.', 'submit': 'Send the completed form for processing.'}),
    17: _item(
        'Check who is signing in',
        'Authentication checks who a person is. A server should not keep readable passwords. A trusted password library stores a specially calculated password hash and checks future sign-ins against it.',
        'Asha signs up with a password. The library stores a salted password hash, so equal passwords do not need identical stored values. '
        'At sign-in, the library checks the entered password. On success, the server creates a session and the browser receives a protected cookie that identifies it.',
        ['Use a maintained password-handling library.', 'Let it create and check password hashes.',
         'Keep the session cookie protected and expire the session when appropriate.'],
        'Should a forgotten-password feature email the original password?',
        'No. The app should offer a protected password-reset flow. It should not have a readable copy to send back.',
        {'authentication': 'Checking who is signing in.', 'password hash': 'A calculated value used to check a password without storing it as readable text.',
         'salt': 'Extra random data used when hashing a password.', 'session': 'A server record of a signed-in visit.',
         'cookie': 'A small value the browser can send back with requests.'}),
    18: _item(
        'Check what a signed-in person may access',
        'Signing in does not give a person access to every saved record. Authorization checks whether this person may do this action. The server must make that check for each protected request.',
        'Asha owns session 12 and Ravi owns session 13. Asha requests session 13 by changing a number in the page address. '
        'The server checks the owner and refuses the request. '
        'Hiding Ravi’s session link on the page would not be enough because a person can send the request directly.',
        ['Find the signed-in person on the server.', 'Check who owns the requested record.',
         'Allow the action only when the permission rule passes.'],
        'Asha is signed in. Does that alone let her delete Ravi’s session?',
        'No. The server must check ownership or another explicit permission before deleting anything.',
        {'authorization': 'Checking whether a person may do a particular action.', 'owner': 'The person or account a record belongs to.',
         'protected route': 'A request address that requires permission checks.'}),
    19: _item(
        'Show a manageable part of a long list',
        'Filtering chooses which records belong in a result. Sorting decides their order. Pagination splits that ordered result into smaller pages so the app does not need to show everything at once.',
        'Study sessions have minutes 10, 40, 20 and 30. Filtering for at least 20 leaves 40, 20 and 30. '
        'Sorting from smallest to largest gives 20, 30, 40. '
        'With two results per page, page one contains 20 and 30; page two contains 40.',
        ['Apply the filter to the complete matching dataset.', 'Sort with a stable tie-breaker, such as the session id.',
         'Return one page from that ordered result.'],
        'Using the same numbers, filter for at least 30 and sort from largest to smallest.',
        'The ordered result is 40, 30. Both fit on the first page when the page size is two.',
        {'filter': 'Select records that meet a rule.', 'sort': 'Put results in a chosen order.',
         'pagination': 'Split a long result into pages.', 'tie-breaker': 'An extra rule for ordering equal values.'}),
    20: _item(
        'Let the page ask a model for a prediction',
        'A model is a saved calculation that produces an estimate from inputs. An API can accept inputs, run that calculation, and return the estimate. The page should describe it as a prediction rather than a guaranteed outcome.',
        'For practice, use the simple rule tomorrow’s minutes = today’s minutes + 5. '
        'The page sends 20, the server checks it, runs the rule, and returns a prediction of 25. '
        'This rule is a demonstration baseline; it has not learned from data or proved that tomorrow’s study time will be 25.',
        ['Define the accepted input and its limits.', 'Run a simple known prediction rule.',
         'Return the estimate with a clear label.'],
        'What should the demonstration API predict for 10 minutes today?',
        '15 minutes. An input such as "hello" should be rejected before the calculation runs.',
        {'model': 'A calculation used to make predictions.', 'prediction': 'An estimate of an unknown result.',
         'baseline': 'A simple starting solution used for comparison.'}),
    21: _item(
        'Show that the prediction feature works',
        'A demonstration should show both a useful result and an understandable failure. Known inputs make the result easy to verify. A prediction feature also needs to state what it cannot promise.',
        'Your demonstration rule adds 5 to today’s study minutes. Entering 20 shows Predicted minutes: 25. '
        'Entering -4 shows Enter minutes above 0, and the prediction calculation does not run. '
        'Explain that the rule demonstrates the connection between page and server; it is not evidence of accurate forecasting.',
        ['Try a valid input and check its exact answer.', 'Try an invalid input and check the error.',
         'Describe one limitation of the prediction.'],
        'Choose one test that catches a calculation mistake and one that catches missing validation.',
        'Check that input 10 gives 15, and that input -4 is rejected. These test different responsibilities.',
        {'demo': 'A short demonstration of how a feature works.', 'validation': 'Checking whether an input is allowed.',
         'limitation': 'Something the feature cannot reliably do.'}),
    22: _item(
        'Let slow work continue after the first reply',
        'Some work takes too long for one page request. The server can save a job and return its identifier quickly. A separate worker performs the job while the page asks for its current status.',
        'Uploading 100 study sessions creates job 42. The first reply says queued, meaning the job is waiting. '
        'Later, a status request for job 42 says running, then completed with 100 saved records. '
        'The page must also handle failed, because accepting a job does not mean it will succeed.',
        ['Create the job and return its id.', 'Let a worker process the saved job.',
         'Show waiting, working, success or failure from its status.'],
        'What should the page say immediately after receiving queued?',
        'Import waiting to start. It should not say 100 sessions saved because the work has not finished.',
        {'background job': 'Work performed separately from the first request.', 'worker': 'A program that performs saved jobs.',
         'queue': 'A list of jobs waiting for workers.', 'status endpoint': 'An API address for checking how work is going.'}),
    23: _item(
        'Stop waiting forever and retry carefully',
        'A timeout limits how long a caller waits. A retry sends another attempt after a problem that may be temporary. Cancellation asks work to stop, but the worker may already have finished part of it.',
        'A job-status request gets no reply within three seconds. The page stops waiting and tries again after a short delay. '
        'Reading status again is safe because it does not create another job. '
        'Pressing Cancel requests cancellation; the page waits for the server to confirm the final job state.',
        ['Set a reasonable waiting limit.', 'Retry only failures and actions that are safe to repeat.',
         'Confirm cancellation instead of assuming it succeeded.'],
        'Should a page create a second import job just because its status request timed out?',
        'No. Ask about the existing job again. A missing reply does not prove that the first job disappeared.',
        {'timeout': 'A limit on how long to wait.', 'retry': 'Try an operation again.',
         'cancellation': 'A request to stop work.', 'temporary failure': 'A problem that may go away without changing the input.'}),
    24: _item(
        'Keep a repeated save from creating duplicates',
        'A save request may arrive twice when a reply is lost. An idempotency key identifies one intended action across repeated attempts. The server remembers that action and avoids applying it twice.',
        'The page sends Add 20 minutes with action key save-7. The server saves one session, but its reply is lost. '
        'The page retries using save-7. The server recognises the same action and returns the saved result rather than adding another 20 minutes. '
        'A different intended session needs a new key.',
        ['Create one key for one intended save.', 'Reuse that key when retrying the same save.',
         'On the server, record the key and result safely with the change.'],
        'Two attempts with key save-7 both request the same 20-minute session. How many sessions should be saved?',
        'One. Repeated attempts should return the same saved result; a reused key with changed input should be rejected.',
        {'idempotent': 'Repeating an action has the same effect as doing it once.',
         'idempotency key': 'An identifier shared by attempts at one intended action.', 'duplicate': 'An extra copy of the same thing.'}),
    25: _item(
        'Show progress while work is running',
        'An event is a message saying that something happened. A worker can send progress events while it imports records. The page updates its display as those messages arrive.',
        'An import job has 100 records. It reports 20 processed, then 50, then 100. '
        'The page shows 20%, 50%, and finally the confirmed result. '
        'If the connection drops after 50, the page asks the server for current status when it reconnects. Silence alone does not mean the job stopped.',
        ['Give each progress message a job id.', 'Update only the matching job on the page.',
         'Read the latest saved status after reconnecting.'],
        'A message says 30 out of 100 records have been processed. What progress should appear?',
        '30%. The page should still show that work is running until it receives a final success or failure state.',
        {'event': 'A message describing something that happened.', 'progress': 'How much of the work has finished.',
         'reconnect': 'Make a connection again after losing it.'}),
    26: _item(
        'Check each row in an imported file',
        'A batch import brings several records into an app together. Each row still needs validation. Choose and explain whether one bad row blocks the whole import or only that row.',
        'A file contains minutes 20, -5 and 30. This import allows valid rows to be saved separately. '
        'Its report says two rows saved and row 2 rejected because minutes must be above 0. '
        'If the product instead requires all rows to succeed together, it should save none and report the error before committing changes.',
        ['State the import’s rule for invalid rows.', 'Check every row and retain its original row number.',
         'Report saved and rejected counts clearly.'],
        'For the partial-save rule, what is the saved total from 20, -5 and 30?',
        '50 minutes. The rejected -5 does not reduce the total, and the user can find it as row 2.',
        {'batch': 'Several items processed together.', 'import': 'Bring information from outside into the app.',
         'partial save': 'Save valid items while reporting rejected ones.'}),
    27: _item(
        'Leave useful notes when the program runs',
        'A log is a saved note about what a program did. Structured logs use named fields so related notes are easier to find. They should help diagnose problems without copying passwords or private document text.',
        'An import log contains job_id: 42, event: row_rejected, row: 2, reason: negative_minutes. '
        'These fields explain where the problem happened without storing the entire uploaded file. '
        'The page shows a helpful message, while the job id lets a developer locate matching server notes.',
        ['Choose an id that connects related notes.', 'Record the action and a short reason for failure.',
         'Leave secret and unnecessary personal values out.'],
        'What two fields would help find the failure of row 8 in job 42?',
        'job_id: 42 and row: 8. Add a useful event and reason, such as invalid_minutes, to explain the failure.',
        {'log': 'A recorded note about a program’s activity.', 'structured log': 'A note organised into named fields.',
         'field': 'One named piece of information.'}),
    28: _item(
        'Connect a queued job from start to finish',
        'A queued service has several visible stages. The first reply confirms acceptance; a later result confirms completion. A complete demonstration should also show how a failed or repeated attempt is handled.',
        'The page submits three sessions and receives job 42. A worker validates them and saves the two valid rows. '
        'The status becomes completed_with_errors with two saved and one rejected. '
        'Reloading the page still finds job 42 and its result, because job status is saved on the server.',
        ['Submit a tiny import and keep its job id.', 'Follow waiting, running and final status.',
         'Reload the page and recover the same result.'],
        'Explain why the first reply should not say Import completed.',
        'At that point the server has only accepted the work. The worker may still be waiting, running, or about to find invalid rows.',
        {'queued': 'Waiting for a worker to start.', 'job id': 'A value that identifies one piece of background work.',
         'final status': 'The saved outcome after work has stopped.'}),
    29: _item(
        'Package the app with what it needs',
        'An app depends on a language runtime and supporting packages. A container image packages these together so another machine can run the same prepared environment. Saved database information usually belongs outside the replaceable container.',
        'Your study app needs a specific Python version and three packages. The build recipe installs their recorded versions and copies the app code. '
        'A container started from the resulting image runs that prepared app. '
        'Replacing the container should not erase study records, which are kept in persistent storage.',
        ['Record the runtime and package versions.', 'Build an image from a written recipe.',
         'Keep durable records separate from replaceable app files.'],
        'If the app container is replaced, which data must still exist?',
        'Saved study sessions and other durable user records. Packaging the code does not by itself protect database data.',
        {'runtime': 'The software that runs a programming language.', 'dependency': 'A package the app needs.',
         'image': 'A prepared package used to start a container.', 'container': 'A running app with an isolated prepared environment.'}),
    30: _item(
        'Run checks whenever code changes',
        'Continuous integration runs agreed checks when someone proposes a code change. A test gate blocks the next step when a required check fails. Passing checks gives useful evidence, although it cannot prove there are no bugs.',
        'A change accidentally makes the total of 20 and 10 become 2010 by joining text. '
        'An automatic test expects the number 30 and fails. The release is blocked until the calculation is corrected. '
        'Another check can verify that a fresh build succeeds before a release is considered.',
        ['Choose checks for important behaviour.', 'Run them automatically on proposed changes.',
         'Investigate a failed required check before releasing.'],
        'Which test would catch a change that saves negative minutes?',
        'Send -5 to the API and check that it rejects the request and creates no row. Checking only a valid save would miss this mistake.',
        {'continuous integration': 'Automatically checking code changes as they are combined.',
         'test gate': 'A required check that must pass before the next step.', 'build': 'Preparing runnable app files from the source code.'}),
    31: _item(
        'Keep settings and secret keys out of the code',
        'The same app may need different settings on different machines. Configuration supplies those settings without changing the program. A secret is a private value, such as a password or a service key, that needs stronger protection.',
        'On your laptop, the app uses a practice database. On the public service, it uses the real database. '
        'The database address comes from configuration. Its password comes from a protected secret store or protected environment setting. '
        'Neither the password nor a private service key should be placed in code sent to the browser.',
        ['Separate ordinary settings from secrets.', 'Supply the correct values when starting the app.',
         'Stop with a clear error if a required setting is missing.'],
        'Can a private API key safely be hidden in a page’s JavaScript file?',
        'No. Browser files can be inspected. Keep the private key on the server and limit what the server allows callers to do.',
        {'configuration': 'Settings supplied to a program.', 'secret': 'A private value that grants access.',
         'environment setting': 'A value given to a program when it starts.'}),
    32: _item(
        'Accept a file and keep it safely',
        'An upload sends a file from a person’s device to the app. Object storage keeps files using identifiers. The app should check the file and its owner before storing it or allowing someone to download it.',
        'Asha uploads notes.txt, which is 2 kilobytes. The app accepts text files up to 100 kilobytes, checks the content, and saves it under a new storage id. '
        'A database row records Asha as its owner. Another learner cannot read it just by guessing the original file name.',
        ['Check the allowed size and file content.', 'Create a storage id instead of trusting the supplied name.',
         'Check ownership when serving the saved file.'],
        'A 200-kilobyte file arrives when the limit is 100. What should happen?',
        'Reject it with a clear size-limit message before accepting the full upload where possible. Do not silently save a broken half-file.',
        {'upload': 'Send a file to the app.', 'object storage': 'A service that stores files by identifier.',
         'kilobyte': 'A unit used to describe the size of a file.', 'owner': 'The account a file belongs to.'}),
    33: _item(
        'Start the app where other people can use it',
        'Deployment puts a prepared app into its running environment. A health check asks whether the app is working well enough for a particular purpose. Being started is different from being ready to serve requests.',
        'The study app starts, but cannot yet reach its database. A simple running check may pass because the process is alive. '
        'A readiness check should fail until the database connection needed for requests works. '
        'Incoming traffic can then be held back instead of sending learners to a page that cannot save anything.',
        ['Start the prepared app with its required settings.', 'Check that required services are available.',
         'Send traffic only when the app is ready.'],
        'Should an app accept save requests before its required database is reachable?',
        'No. It should report that it is not ready. A running process alone does not show that saving works.',
        {'deployment': 'Putting an app into the place where it runs.', 'health check': 'A small check of an app’s condition.',
         'readiness': 'Whether an app can handle incoming work.', 'traffic': 'Requests arriving at the app.'}),
    34: _item(
        'Notice a bad release and restore a working one',
        'A release is a particular version of the app made available to users. Monitoring checks how it behaves after release. A rollback returns to an earlier version when the new one causes problems.',
        'Before release, 1 out of 100 save requests fails. After release, 20 out of 100 fail. '
        'That jump is a reason to investigate and possibly restore the previous app version. '
        'First check that the old code can still use the current database structure; changing the code back does not automatically undo stored data changes.',
        ['Record normal error and response-time levels.', 'Compare them after the release.',
         'Restore a known working version when the rollback plan is safe.'],
        'What should you check after rolling back the app?',
        'Confirm that real save requests work again and error levels recover. A successful restart alone is not enough evidence.',
        {'release': 'A version made available to users.', 'monitoring': 'Watching measurements of a running app.',
         'rollback': 'Return to an earlier working version.'}),
    35: _item(
        'Demonstrate a deployed prediction app',
        'A deployed demonstration should work from a fresh browser visit. It needs clear input instructions, a useful result, and an understandable error. Keep a record of the version being demonstrated so the result can be investigated later.',
        'Open the study prediction page without relying on an old browser session. Enter 20 minutes and receive the expected demonstration prediction of 25. '
        'Try text in the number box and check the error. '
        'Finally, check the running version and confirm that a failed prediction does not leave the page permanently waiting.',
        ['Open the deployed address in a fresh visit.', 'Try one valid and one invalid input.',
         'Check recovery after a failed request.'],
        'What three things should you record for this demonstration?',
        'The deployed version, the inputs you tried, and the results you observed. These make a later report more useful than It worked for me.',
        {'deployed app': 'An app running where its intended users can reach it.', 'version': 'A label for a particular set of app changes.',
         'recovery': 'Returning to a usable state after a problem.'}),
    36: _item(
        'Show an answer as its pieces arrive',
        'A streamed reply arrives in pieces rather than all at once. The page can show each piece as it arrives. It must still know whether the reply finished, failed, or was stopped.',
        'An assistant sends Study, then for 20, then minutes. The page joins the pieces into Study for 20 minutes. '
        'A separate finished signal marks the answer complete. '
        'If the connection breaks after Study for 20, the page labels the answer incomplete instead of pretending it is the full reply.',
        ['Create one place to collect pieces for this request.', 'Append each arriving piece in order.',
         'Show a clear completed or interrupted state.'],
        'Pieces arrive as Read, one, and chapter, with spaces between them. What should the final answer show?',
        'Read one chapter. It should be marked complete only after the server confirms that the reply has finished.',
        {'stream': 'Information sent in pieces over time.', 'server event': 'An update sent from the server to the page.',
         'incomplete': 'Missing part of the expected result.'}),
    37: _item(
        'Stop an old request from replacing a new answer',
        'An asynchronous request lets the page keep working while it waits. Requests do not always finish in the order they started. The page should connect each reply to the question that caused it.',
        'A learner searches for py, then quickly changes the search to python. '
        'The python reply arrives first. A slower py reply arrives later. '
        'The page keeps the python results by checking the current request id. It may also ask to cancel the older request, but should not rely on cancellation always arriving in time.',
        ['Give each new search a request id.', 'Ask to cancel work that is no longer needed.',
         'Show a reply only if it still belongs to the current search.'],
        'Which reply should remain visible if the older search finishes last?',
        'The reply for the current search, python. Arrival order should not decide what the learner meant to search for.',
        {'asynchronous': 'Work that can finish later while other work continues.',
         'request id': 'A value used to identify one request.', 'stale result': 'An answer to a request that is no longer current.'}),
    38: _item(
        'Limit how many tasks run together',
        'Concurrency means handling more than one task during the same period. A connection pool keeps a limited set of reusable database connections. Limits stop one busy feature from using every available resource.',
        'The app has three database connections and five requests arrive. Three requests can use connections while two wait. '
        'When a connection is returned, another request can use it. '
        'If waiting lasts too long, the app returns a clear temporary error instead of allowing the waiting list to grow forever.',
        ['Choose a connection limit the database can support.', 'Return each connection after use, even after errors.',
         'Limit how long requests can wait.'],
        'With three connections already in use, should a fourth request create unlimited extra connections?',
        'No. It should wait within a limit or receive a temporary failure. A pool is useful because it controls this resource.',
        {'concurrency': 'Handling several tasks during overlapping time.', 'connection': 'A communication link to another service.',
         'pool': 'A limited collection of reusable resources.', 'resource': 'Something work needs, such as memory or a connection.'}),
    39: _item(
        'Describe the shape of an API reply',
        'A type describes what kind of value a program expects. A typed API client gives page code a clear description of requests and replies. It helps catch mistakes while writing code, but outside data still needs checks when it arrives.',
        'A session reply should contain id as a number and title as text. '
        'The client description helps warn a developer who tries to use title as a number. '
        'If a broken server actually sends title: 42, a runtime check must catch that mismatch; a type written in the page code does not transform the received value.',
        ['Write the expected names and value kinds.', 'Use that description when calling the API.',
         'Check received data before displaying or using it.'],
        'The reply should contain minutes as a number but sends "twenty". Is the description enough?',
        'No. A check of the actual reply must reject or handle the invalid value.',
        {'type': 'A description of a value’s kind or shape.', 'API client': 'Code that sends requests to an API.',
         'runtime check': 'A check performed while the program runs.'}),
    40: _item(
        'Check an AI reply before using its values',
        'An AI reply can look correct and still contain unusable values. A schema describes the allowed names, value kinds, and limits. Check the real reply against those rules before saving it or taking an action.',
        'An assistant should return a study title and minutes from 1 to 120. '
        'It returns {"title": "Reading", "minutes": -5}. The text format is valid, but the minutes break the rule. '
        'The app rejects this suggestion and asks for a corrected result or shows a helpful error.',
        ['Define the required fields and limits.', 'Read the reply as structured data.',
         'Check the values before using them.'],
        'Would {"title": "Reading", "minutes": 20} pass these two checks?',
        'Yes: the title is text and 20 is within 1 to 120. Passing these checks still does not prove the suggestion is educationally useful.',
        {'schema': 'Rules describing the allowed shape and values of data.',
         'structured data': 'Information organised into named parts.', 'validation': 'Checking actual values against rules.'}),
    41: _item(
        'Give people a useful next step after failure',
        'A fallback is a simpler option used when the preferred feature is unavailable. It should be clearly labelled so the user knows what they received. An error message should explain the immediate problem and a safe next step.',
        'The AI study planner is unavailable. The page says We could not create a new plan. '
        'It offers a saved plan from yesterday, labelled Saved plan from yesterday, and a Try again button. '
        'It does not describe the old plan as freshly generated. The learner can still read their saved sessions.',
        ['Keep the rest of the page usable.', 'Name the unavailable feature in simple words.',
         'Offer a clearly labelled alternative when one is useful.'],
        'Write a message for a failed answer stream that already showed half an answer.',
        'The answer stopped before it finished. Try again. Keep the partial answer clearly marked as incomplete.',
        {'fallback': 'A simpler option used when the usual one is unavailable.',
         'partial answer': 'Only part of the intended answer.', 'retry': 'Try the same operation again.'}),
    42: _item(
        'Check a streamed assistant from start to finish',
        'A streamed assistant needs more than text appearing on the screen. It must keep replies separate, handle interruption, and stop old requests changing the current answer. Test these behaviours with small predictable replies.',
        'A test sends the pieces Read, one, and page, then a finished signal. The page should show Read one page as complete. '
        'A second test sends Read, then an error. The page should show an interrupted answer. '
        'A third starts a new question and checks that late pieces from the old question are ignored.',
        ['Test normal pieces and the final signal.', 'Test a broken connection halfway through.',
         'Test a new question arriving before the old one finishes.'],
        'What distinguishes a finished answer from an interrupted answer in these tests?',
        'The server’s final signal. The existence of some visible text does not prove the answer is complete.',
        {'stream': 'A reply delivered in pieces.', 'interruption': 'Work stopping before its expected end.',
         'request isolation': 'Keeping the data from one request separate from another.'}),
    43: _item(
        'Read useful text from an uploaded document',
        'A document file contains text and sometimes layout or pictures. Parsing reads its format and extracts usable information. The app should tell the learner when it cannot read the content, rather than treating an empty result as success.',
        'A text note contains Exam on Friday. The importer reads those words and saves them with the file’s owner and name. '
        'A scanned page may contain only a picture of words. A plain text reader may extract nothing from it. '
        'The app then explains that this file needs a supported text-reading method.',
        ['Check that the file format is supported.', 'Extract and inspect the text.',
         'Keep the source and owner attached to the result.'],
        'What should happen if an importer extracts no text from a nonempty file?',
        'Report that no readable text was found and explain the supported formats. Do not claim the document is ready to search.',
        {'parsing': 'Reading a file’s format to extract its parts.', 'format': 'The way information is arranged in a file.',
         'source': 'Where the information came from.'}),
    44: _item(
        'Split a long document into useful pieces',
        'A long document can be easier to search when divided into smaller pieces called chunks. Each piece should keep enough surrounding words to make sense. Metadata records where that piece came from and who may read it.',
        'A study guide has a page about exam dates and another about fees. Save these as separate chunks. '
        'The exam chunk keeps document id 8, page 1, and its owner. '
        'Searching for the exam date can return that small piece while still linking back to the original page.',
        ['Split at sensible boundaries, such as paragraphs.', 'Keep headings with the text they explain.',
         'Attach the source page and access information to every piece.'],
        'Why is a piece containing only Friday less useful than The exam is on Friday?',
        'Friday alone does not say what happens that day. The longer piece preserves the meaning needed to answer a question.',
        {'chunk': 'A smaller piece of a larger document.', 'metadata': 'Details about information, such as its source page.',
         'boundary': 'The place where one piece ends and the next begins.'}),
    45: _item(
        'Return document pieces that match a question',
        'Retrieval means finding useful stored information for a question. A retrieval API accepts a question and returns matching document pieces. It must search only information the requesting person is allowed to read.',
        'Asha asks When is my exam? Her notes include The exam is on Friday and The fee is 50 rupees. '
        'The search returns the exam sentence with its source page. '
        'Ravi’s private exam note is not included, even if it contains an exact match for the question.',
        ['Identify the person making the request.', 'Search only documents they may access.',
         'Return a few useful pieces with their sources.'],
        'Which of Asha’s two sentences should be ranked first for the exam-date question?',
        'The exam is on Friday. It directly answers the date question, while the fee sentence is about a different detail.',
        {'retrieval': 'Finding stored information relevant to a request.', 'rank': 'Put matches in order of usefulness.',
         'endpoint': 'An API address for a particular kind of request.'}),
    46: _item(
        'Make document search easy to use',
        'A search page should show what question was searched and where each match came from. Filters can narrow results to selected documents. Pagination keeps a long list manageable, and an empty result needs a helpful explanation.',
        'Searching exam returns eight pieces from three documents. Choosing the Biology notes filter leaves three pieces. '
        'With two results per page, the first page shows two and the next page shows one. '
        'Changing the filter returns to the first page so the learner does not remain on a page that no longer exists.',
        ['Show the current question and selected filters.', 'Display a short excerpt and source for each match.',
         'Reset the page position when the search changes.'],
        'Write the message when no permitted document matches a search.',
        'No matching text found. Try different words or choose another document. Do not expose the names of inaccessible files.',
        {'excerpt': 'A short piece of a longer text.', 'filter': 'A rule that narrows the results.',
         'pagination': 'Showing a long result in smaller pages.'}),
    47: _item(
        'Show where an answer’s claim comes from',
        'A citation points to the source supporting an answer. It helps a person check a claim. Adding a link is not enough: the linked text must actually support what the answer says.',
        'The source says The exam starts on Friday at 10 am. The answer says Your exam starts on Friday at 10 am and links to that page. '
        'This is supported. An answer saying The exam lasts three hours is not supported by the same sentence because the source gives no duration.',
        ['Keep source ids with the retrieved text.', 'Link claims to the pieces that support them.',
         'Avoid claims the available text does not establish.'],
        'Can the source sentence support a claim that the exam ends at 1 pm?',
        'No. It gives the start time but no length or end time. The answer should say that the end time was not found.',
        {'citation': 'A reference to evidence for a claim.', 'claim': 'Something an answer says is true.',
         'supported': 'Backed by the available evidence.'}),
    48: _item(
        'Check search with a small set of known questions',
        'An evaluation set contains questions with known useful answers or sources. A runner repeats those checks after a change. Keep search quality separate from answer wording so you can find which part caused a mistake.',
        'Use three questions: exam date, fee, and classroom. The notes contain the date and fee but no classroom. '
        'The search should find the right source for the first two. The assistant should admit missing evidence for the third. '
        'If the date source is absent from the search results, changing answer wording alone will not fix the problem.',
        ['Write a few questions and their expected sources.', 'Include a question the notes cannot answer.',
         'Run the same checks after each change.'],
        'What should the expected answer be for classroom when no note mentions it?',
        'The classroom was not found in the available notes. Inventing a room number must fail the check.',
        {'evaluation set': 'Examples used to measure how well a feature works.',
         'runner': 'A program that performs a set of checks.', 'expected source': 'The document piece a question should find.'}),
    49: _item(
        'Demonstrate a document assistant with evidence',
        'A document assistant should show both useful answers and clear limits. Its demonstration should connect an uploaded document to a searched piece and a cited answer. Known questions make that journey easy to check.',
        'Upload a note saying The exam is Friday. Ask When is the exam? and check that the answer says Friday with the correct source. '
        'Then ask What is the classroom? The answer should say the information was not found. '
        'Finally, check that another account cannot retrieve this private note.',
        ['Upload one short document with two known facts.', 'Ask a supported question and open its citation.',
         'Try a missing fact and an access check.'],
        'What evidence would show the assistant used the wrong document?',
        'Its citation opens a document that does not support the answer, or belongs to an account without access. Both are meaningful failures.',
        {'citation': 'A link to the evidence behind an answer.', 'access check': 'A check of who may read or change information.',
         'missing fact': 'Information not present in the available sources.'}),
    50: _item(
        'Describe a task as clear steps and states',
        'A workflow is a task with several steps. A state describes where that task is now. Allowed transitions say which state may follow another, preventing the app from skipping required work.',
        'A study-report workflow moves from draft to checked to approved to sent. '
        'A report with missing minutes stays in draft until corrected. '
        'A checked report may wait for approval, but it must not jump straight to sent. Saving the current state lets the page show the next useful action.',
        ['Write the possible states.', 'Draw the allowed moves between them.',
         'Name the checks required before each move.'],
        'A report is checked but has no approval. Which state should come next?',
        'It should remain checked or wait for approval. It can become approved only after the required person approves that report.',
        {'workflow': 'A task organised into connected steps.', 'state': 'The current stage of a task.',
         'transition': 'An allowed move from one state to another.'}),
    51: _item(
        'Check the values passed to a tool',
        'A tool is a function an assistant can ask the app to run. The app must check the requested values and permissions before running it. A model’s request is a suggestion, not proof that the action is allowed.',
        'A save_session tool needs a title and minutes from 1 to 120. The assistant requests title Reading and minutes 20. '
        'The server checks the values and saves under the signed-in account. '
        'If the request includes another person’s account id, the server does not simply trust that supplied owner.',
        ['Describe the tool’s required fields and limits.', 'Validate the actual values on the server.',
         'Apply the signed-in person’s permissions before execution.'],
        'The assistant requests a session of -5 minutes. Should the tool run because an AI requested it?',
        'No. Reject the invalid input with a clear reason. The same rules apply to human-entered and AI-supplied values.',
        {'tool': 'A function an assistant can request.', 'tool input': 'The values given to that function.',
         'execution': 'Actually running the requested work.'}),
    52: _item(
        'Give an assistant a clear stopping point',
        'An assistant that can call tools needs limits on time and number of actions. Otherwise a mistake can repeat for too long. Cancellation should stop new work and record what already happened.',
        'A study assistant may make at most three search calls for one question. It searches twice without useful results. '
        'After the third unsuccessful search, it stops and explains that it could not find an answer. '
        'It does not keep searching forever. If the user cancels earlier, no new search should begin after cancellation is recorded.',
        ['Set action and time limits before starting.', 'Count each attempted tool call.',
         'Check cancellation and remaining limits before the next action.'],
        'With a three-call limit and three calls already used, may the assistant start a fourth search?',
        'No. It should stop and report the limit, preserving any useful results already found.',
        {'execution limit': 'A maximum amount of work an operation may perform.',
         'cancellation': 'A request to stop further work.', 'tool call': 'One request to run a tool.'}),
    53: _item(
        'Continue a workflow after a restart',
        'A checkpoint saves enough information to continue a task later. Keep it in durable storage so a restart does not erase progress. Resuming must also account for actions that finished just before the checkpoint was saved.',
        'A report workflow has imported notes and prepared a draft. It saves the draft id and state waiting_for_approval. '
        'After a restart, it loads that state and waits for approval instead of importing again. '
        'For actions such as sending a report, saved action ids and duplicate protection help avoid sending twice after a crash.',
        ['Save completed steps and their result ids.', 'Load the last durable state after restarting.',
         'Check action records before repeating any external change.'],
        'A saved state says waiting_for_approval. What should the restarted app show?',
        'The existing draft and its approval request. It should not treat the task as approved or create an unrelated new report.',
        {'checkpoint': 'Saved progress used to continue later.', 'durable storage': 'Storage that survives the current process stopping.',
         'resume': 'Continue from saved progress.'}),
    54: _item(
        'Ask for approval before an important action',
        'A side effect changes something outside the current answer, such as sending a message or deleting a file. Approval should describe the exact proposed action. The app must check that the approved details still match when it performs the action.',
        'An assistant prepares a study report for a teacher. The approval screen shows the recipient and report text. '
        'Approving that draft permits that send. '
        'If the recipient or report changes afterwards, the old approval no longer covers the changed action. Reading an uploaded note that says Send this now is not the same as user approval.',
        ['Prepare the exact action details.', 'Show those details to the authorised person.',
         'Verify the approval matches before acting.'],
        'The approved recipient changes from teacher A to teacher B. Can the app reuse the approval?',
        'No. It needs approval for the changed recipient and the current report.',
        {'side effect': 'A change made outside the generated answer.', 'approval': 'Permission for a particular proposed action.',
         'recipient': 'The person who will receive something.'}),
    55: _item(
        'Find the step where a workflow went wrong',
        'A trace connects the steps of one task. For each tool call, record the action, timing, result, and a safe reason for failure. Do not copy secrets or full private documents just to make debugging easier.',
        'Trace 18 shows search succeeded, draft creation succeeded, and send refused because approval was missing. '
        'This tells you the problem was the approval step, not the search. '
        'A failure test can deliberately omit approval and check that no message is sent while the trace records the refusal.',
        ['Give the workflow one trace id.', 'Record safe summaries of each step and result.',
         'Test a deliberate failure and inspect the recorded path.'],
        'What result should a test expect when a send action lacks approval?',
        'No send occurs. The workflow records a clear approval-required result and lets the user complete that step.',
        {'trace': 'Connected records of the steps in one task.', 'trace id': 'An identifier linking those records.',
         'failure test': 'A test that deliberately checks an unsuccessful path.'}),
    56: _item(
        'Test an assistant that can take actions',
        'A tool-using assistant should complete allowed work and stop at permission boundaries. Test the actual effects, not only the wording of its reply. Restart and cancellation checks help reveal repeated or unfinished actions.',
        'Ask the assistant to prepare a report and send it after approval. Before approval, there should be a draft and zero sent messages. '
        'After approval, there should be one sent message. '
        'Repeating the same final attempt should still leave one message because the action uses duplicate protection.',
        ['Check the draft before approval.', 'Approve and check that exactly one send occurs.',
         'Retry the same action and check that it is not repeated.'],
        'The assistant says I waited for approval, but a message was already sent. Did the test pass?',
        'No. The real effect broke the rule. A reassuring sentence cannot replace checking what the tool actually did.',
        {'side effect': 'An actual change, such as sending a message.', 'permission boundary': 'The point beyond which an action needs additional permission.',
         'duplicate protection': 'A check that prevents the same intended action being applied twice.'}),
    57: _item(
        'Check training data before the model uses it',
        'A training pipeline is a sequence of steps that prepares data and fits a model. Bad inputs can make its results misleading. Check required columns, allowed values, missing information, and repeated records before training.',
        'A study dataset requires learner_id, minutes_today and minutes_tomorrow. '
        'One row lacks minutes_today and another has -10. The pipeline reports both problems before training. '
        'If it silently treats missing minutes as zero, it changes the meaning of the data and may teach the model a false pattern.',
        ['Write rules for each required column.', 'Check the dataset and report problem counts.',
         'Stop or apply an explicitly chosen repair rule before training.'],
        'Is a missing minutes value always the same as a recorded zero minutes?',
        'No. Missing means unknown; zero means no minutes were recorded as studied. Any replacement rule needs a clear reason.',
        {'pipeline': 'A sequence of steps that pass results to the next step.',
         'training': 'Using examples to adjust a model.', 'missing value': 'Information that was not provided.'}),
    58: _item(
        'Receive records together or as they happen',
        'Ingestion means bringing new data into a system. A batch brings many records at once; an event brings a record when something happens. Both need clear rules for duplicates, errors, and arrival time.',
        'A school uploads yesterday’s 100 study sessions each morning: that is a batch. '
        'A study app sends one session when Save is pressed: that is event-based ingestion. '
        'If either sender retries session id 7, the receiving system must recognise the repeated record rather than counting it as extra study time.',
        ['Choose when the data needs to become available.', 'Give incoming records stable identifiers.',
         'Check and record accepted, rejected and repeated items.'],
        'Which approach fits a report that only needs yesterday’s completed study totals?',
        'A daily batch may be enough. Sending every event immediately is useful only if the product needs fresher information.',
        {'ingestion': 'Receiving data into a system.', 'batch': 'A group of records received together.',
         'event': 'A record that something happened.', 'freshness': 'How recently the available data was updated.'}),
    59: _item(
        'Record which data and model made a result',
        'A version identifies a particular saved model or dataset. Recording versions helps you repeat an experiment and investigate a prediction. A model file alone may not tell you how its inputs were prepared.',
        'Experiment A uses dataset 3, preparation code 5, and model 2. A prediction record keeps model version 2. '
        'Next week, experiment B uses a cleaned dataset 4 and model 3. '
        'Keeping the old versions lets you compare them without accidentally describing the new data as the data used by the old model.',
        ['Save dataset and preparation-code versions.', 'Give the trained model its own version.',
         'Record the serving model version with useful prediction records.'],
        'What is missing if your experiment note says only model 2?',
        'The data version, preparation steps and training settings. These can change the result even when the model’s name is the same.',
        {'version': 'An identifier for a particular saved form of something.',
         'reproducible': 'Recorded well enough for someone to repeat the process.', 'preparation': 'Steps that turn raw inputs into model-ready values.'}),
    60: _item(
        'Make predictions in manageable groups',
        'Inference means running a model to produce predictions. Batch inference handles several inputs together. Smaller groups help keep memory and other resource use within safe limits.',
        'You need predictions for 100 study records. With a batch size of 20, the worker handles five groups. '
        'It keeps each prediction linked to its input id, then saves the group result. '
        'If group four fails, a recorded checkpoint and safe repeated writes can help resume without losing or doubling the first three groups.',
        ['Choose a batch size that fits available memory.', 'Keep input ids attached to outputs.',
         'Record progress after each successfully saved group.'],
        'How many groups are needed for 45 records with a maximum of 20 per group?',
        'Three groups: 20, 20 and 5. The final group does not need to be full.',
        {'inference': 'Using a model to make a prediction.', 'batch size': 'The number of inputs handled in one group.',
         'memory': 'Working space a running program uses.'}),
    61: _item(
        'Watch answer quality and waiting time separately',
        'A dashboard can track whether a model is useful and whether the app is fast enough. These are different questions. Fast wrong answers are still wrong, and accurate answers can still arrive too late to help.',
        'On 10 checked study predictions, eight are within your chosen error limit. The quality result is 8 out of 10 for that sample. '
        'Most requests take one second, but one takes eight seconds. '
        'Record both answer quality and the spread of waiting times so the slow request is not hidden by a single average.',
        ['Define what counts as a useful answer.', 'Measure waiting time from request to result.',
         'Show sample sizes and recent changes beside the measurements.'],
        'If answers become faster but only five of the same 10 checks pass, is the new version clearly better?',
        'No. It traded answer quality for speed. Decide whether that trade is acceptable for the actual user task.',
        {'quality measure': 'A check of how useful or correct results are.', 'latency': 'How long a request takes.',
         'sample size': 'How many examples were measured.'}),
    62: _item(
        'Try a new model with a limited release',
        'A new model should be checked before all users depend on it. A canary release sends a small part of suitable traffic to the new version first. Compare quality, errors and speed, and keep a safe path back to the old version.',
        'Model 2 handles most study predictions. Model 3 initially handles a small selected share. '
        'Both versions are recorded with their results. If model 3 produces many invalid replies, stop routing new requests to it. '
        'Restoring model 2 is easier when input preparation and saved data remain compatible with it.',
        ['Pass known evaluation checks before release.', 'Start with limited traffic and monitor outcomes.',
         'Restore the previous version if agreed limits are broken.'],
        'What should you retain before replacing model 2?',
        'Its saved model, required preparation code and settings, plus a tested way to route requests back to it.',
        {'canary release': 'Trying a new version with a small share of traffic first.',
         'routing': 'Choosing which version receives a request.', 'compatible': 'Able to work together correctly.'}),
    63: _item(
        'Explain a model pipeline from input to monitoring',
        'A monitored pipeline connects incoming data, checks, a versioned model, saved predictions and measurements. Each step should leave enough information to explain its result. A broken early step should not quietly become a believable final answer.',
        'Session 7 arrives with 20 minutes. Validation accepts it. Preparation version 2 formats it for model 3, which predicts 25. '
        'The saved result records the session id and model version. '
        'A dashboard measures response time now and prediction quality later when the real outcome becomes available.',
        ['Trace one record through every step.', 'Write the version and result produced at each stage.',
         'Try one invalid record and locate where it stops.'],
        'Why can waiting time be measured before the prediction’s real-world accuracy?',
        'The request finishes now, so its duration is known. Accuracy may require tomorrow’s actual study minutes, which are not known yet.',
        {'pipeline': 'Connected processing steps.', 'monitoring': 'Watching a running system’s behaviour.',
         'outcome': 'What actually happened, used to check an earlier prediction.'}),
    64: _item(
        'Show useful study recommendations',
        'A recommendation suggests an item a person might find useful. An API can return the suggested items and a short explanation. The page should still let the person choose rather than treating a suggestion as a command.',
        'A learner has completed Python variables and functions. A simple rule recommends Lists next because that lesson builds on both. '
        'The API returns the lesson id, title and reason. '
        'The page shows Continue with Lists and explains why. A learner with no history receives a clearly labelled beginner starting lesson.',
        ['Choose a simple recommendation rule.', 'Return useful item details and a truthful reason.',
         'Handle learners with no history.'],
        'What could the page show when there is not enough history for a personalised suggestion?',
        'Start with Python values: a beginner starting point. Do not claim it is based on previous study when no such history exists.',
        {'recommendation': 'A suggestion of something potentially useful.', 'history': 'Recorded earlier actions.',
         'personalised': 'Adjusted using information about a particular person.'}),
    65: _item(
        'Load a long list without repeating expensive work',
        'An efficient query asks for the information the page actually needs. A cursor marks where the next page should continue. A stable order helps keep page boundaries clear when several records have equal values.',
        'Lessons have ids 10, 11, 12, 13 and 14 in increasing order. The first page requests three and receives 10, 11 and 12. '
        'Its cursor records 12 as the last id. '
        'The next request asks for ids greater than 12 and gets 13 and 14. This simple example uses a fixed, unique ordering.',
        ['Choose a stable order with a unique tie-breaker.', 'Request only the needed columns and page size.',
         'Use the last returned position for the next page.'],
        'After receiving ids 10, 11 and 12, should the next page include id 12 again?',
        'No. For this increasing-id example, continue after 12. More complex changing lists need additional rules to define a consistent view.',
        {'query': 'A request for database information.', 'cursor': 'A saved position for continuing through results.',
         'unique': 'Different for every item in the relevant set.'}),
    66: _item(
        'Record feedback without collecting more than needed',
        'Feedback helps show whether a recommendation was useful. Record the meaning of the action clearly. Opening a lesson, finishing it, and saying it helped are different signals.',
        'A learner opens recommended lesson 12 and later presses Helpful. The app records two different events: opened and helpful. '
        'It keeps the lesson id and permitted account link needed for the feature. '
        'It does not copy the learner’s private notes into the feedback event because those notes are unnecessary for counting helpful votes.',
        ['Choose which action you need to understand.', 'Record only the values needed for that purpose.',
         'Keep access controls and repeated-event checks in place.'],
        'Can one opened event prove that a learner understood the lesson?',
        'No. It proves only that the lesson was opened. Understanding needs a different check, such as a short practice answer.',
        {'feedback': 'Information about how a person responded to a feature.', 'signal': 'An observation used as a clue.',
         'event': 'A record of one action or occurrence.'}),
    67: _item(
        'Count an event once even if it arrives twice',
        'A sender may repeat an event when it does not receive confirmation. Deduplication recognises the repeated identifier and avoids counting it twice. Recording the identifier and updating the count must work together safely.',
        'A helpful vote arrives with event id vote-8 and the total becomes 11. The confirmation is lost, so vote-8 arrives again. '
        'The receiver sees that this id was already processed and leaves the total at 11. '
        'A genuinely different vote with id vote-9 can increase it to 12.',
        ['Give each real event a stable id.', 'Check and record that id together with the count update.',
         'Return a useful confirmation for repeated deliveries.'],
        'Starting from 4 votes, event ids A, A and B arrive. What should the total become?',
        '6. A contributes one vote despite arriving twice; B contributes one more.',
        {'deduplication': 'Removing or ignoring repeated copies of the same item.',
         'delivery': 'One attempt to send an event to a receiver.', 'event id': 'An identifier for one real event.'}),
    68: _item(
        'Control who sees a new feature',
        'A feature flag is a setting that switches a feature on or off. An experiment compares planned versions using separate groups. A person should normally keep the same group during the experiment so their experience stays consistent.',
        'A study app compares recommendation A with recommendation B. A stable assignment puts learner 7 in group A for the whole experiment. '
        'Reloading does not move them to B. '
        'A separate flag can disable the new feature if it breaks. Compare completion and errors, not just which group clicked more.',
        ['Define the versions and the result you want to measure.', 'Assign eligible learners consistently.',
         'Record the shown version and watch for harmful changes.'],
        'Why is choosing a new group on every page reload a problem?',
        'One learner sees mixed versions, so their experience becomes confusing and their outcomes are harder to attribute to a version.',
        {'feature flag': 'A setting that controls whether a feature is available.',
         'experiment group': 'People assigned to one version being compared.', 'assignment': 'The rule deciding which version a person sees.'}),
    69: _item(
        'Follow a deletion request through stored copies',
        'A delete action may involve more than one database row. Copies can exist in uploaded files, search indexes and temporary caches. Define which copies the product keeps, remove the active copies as promised, and show whether the work is still running.',
        'A learner deletes notes document 8. The app removes access to the document, then deletes its stored file and searchable pieces. '
        'It also clears related cached results. '
        'If background removal is still running, the page shows that status. Backup handling follows the service’s stated retention and restoration rules.',
        ['List the places that contain the document or its derived text.', 'Block further access and remove the active copies.',
         'Record the removal result and handle failures.'],
        'Is deleting only the document’s visible list entry enough?',
        'No. Its file or search results might remain accessible. Check the related storage locations and permissions too.',
        {'cache': 'A temporary saved copy used for speed.', 'search index': 'Stored information used to find matching content.',
         'retention': 'How long information is kept.'}),
    70: _item(
        'Check whether recommendations help learners',
        'A recommendation demo should explain the reason for a suggestion and measure a useful result. More clicks alone do not prove better learning. Include learners with no history and learners who reject a suggestion.',
        'Ten learners see a suggested lesson. Six open it, but only two finish its practice. '
        'The click result is 6 out of 10; the practice-completion result is 2 out of 10. '
        'These describe different behaviour. A better next experiment might explain prerequisites more clearly instead of simply making the button brighter.',
        ['Show one recommendation and its reason.', 'Check the no-history and dismiss paths.',
         'Report a learning-related outcome alongside clicks.'],
        'If clicks rise but practice completion falls, can you call the change an improvement without more thought?',
        'No. Compare it with the original learning goal and investigate why people open the lesson but stop.',
        {'outcome': 'A result you actually care about.', 'completion rate': 'The share of people who finish a defined task.',
         'prerequisite': 'Something a person needs to know or do first.'}),
    71: _item(
        'Choose one small final project journey',
        'A capstone is a project that combines what you have learned. Keep its first version focused on one useful user journey. Write what success looks like before choosing extra features.',
        'Choose a private notes assistant. Its first journey is: sign in, upload one text note, ask a question, read an answer with a source. '
        'Success means a known question returns the correct fact and source, while another account cannot read the note. '
        'Voice calls and many file formats can wait until this journey works.',
        ['Name the person and the problem.', 'Draw the few steps they need to finish.',
         'Write two checks that prove the journey works.'],
        'Write a success check for a note saying The exam is Friday.',
        'Ask When is the exam? and expect Friday with a link to that note. Also check a question the note cannot answer.',
        {'capstone': 'A final project joining several learned skills.', 'user journey': 'The steps a person follows to reach a result.',
         'scope': 'The work included in the current version.'}),
    72: _item(
        'Build the basic journey before adding AI',
        'A working page and API give the project a clear foundation. Start with known saved information so you can check each connection. Make waiting, empty and error states understandable before adding an unpredictable answer generator.',
        'Create a page that lists saved notes and a server request that returns them. With no notes, show Upload your first note. '
        'After uploading a note titled Exam, the list shows Exam. '
        'Reloading should still show it. This proves the basic saving and reading journey before question answering is connected.',
        ['Build the empty notes page.', 'Save and list one small note through the API.',
         'Reload and check that the saved note remains.'],
        'What should the page show when the notes request fails?',
        'A message such as Could not load notes. Try again. Do not show an empty collection as if the account definitely has no notes.',
        {'frontend': 'The page a person uses.', 'API': 'An agreed way to request data or work from another program.',
         'empty state': 'The page shown when there are no records yet.'}),
    73: _item(
        'Connect the AI step to the working app',
        'Add the AI capability at one clear point in the existing journey. Keep input checks, permissions and result checks around it. If the AI service fails, the rest of the app should remain usable.',
        'The learner asks When is the exam? The server checks access, retrieves the note saying Friday, and supplies that text to the answer step. '
        'It returns an answer with the source id. '
        'If the answer step is unavailable, the page can still show the retrieved note and explain that a generated answer could not be created.',
        ['Start from the already working question request.', 'Add the permitted evidence and answer step.',
         'Check the returned values and show a clear failure if needed.'],
        'What should happen if the AI answer refers to a source id that was never retrieved?',
        'Do not present it as a valid citation. Reject or handle the unsupported reference and keep the failure understandable.',
        {'retrieval': 'Finding useful stored text.', 'citation': 'A reference to supporting source text.',
         'fallback': 'A useful simpler option when the main feature fails.'}),
    74: _item(
        'Check the final project’s boundaries',
        'A project needs checks for more than the happy path. Test invalid inputs, missing permissions, and failures of services it depends on. Each test should verify what happened to saved data as well as what the page said.',
        'Asha uploads a note and can ask questions about it. Ravi requests Asha’s note id directly and is refused. '
        'An empty upload is rejected without creating a searchable document. '
        'A failed answer request leaves the existing note intact and shows a retry option.',
        ['Write one successful journey test.', 'Try another account’s private record.',
         'Try an invalid upload and an unavailable answer service.'],
        'A refused upload leaves an empty searchable document behind. Is that a complete rejection?',
        'No. The operation left unwanted saved state. The test should check that no usable document was created, or that cleanup is explicitly tracked.',
        {'happy path': 'The ordinary case where every required step succeeds.',
         'boundary': 'Where information or permission rules must be checked.', 'dependency': 'Another service or package the feature needs.'}),
    75: _item(
        'Deploy the project and measure one real journey',
        'A deployed project needs evidence from its running environment. Measure a small known journey and record the conditions. Avoid describing a tiny local test as proof that the app can handle many real users.',
        'In the deployed notes assistant, upload one short test note and ask the same known question five times. '
        'Record whether each answer is supported, how long each request takes, and which version ran. '
        'If all five pass, report five successful checks under these conditions; that does not establish accuracy for every possible document.',
        ['Confirm the deployed version and required settings.', 'Run a known journey several times.',
         'Record results, timings and the limits of the test.'],
        'How should you describe a test where four of five known questions passed?',
        'Four of five checked questions passed in this test set. Include the failed question and what made its answer fail.',
        {'measurement': 'A recorded observation of a result.', 'latency': 'The time from a request to its result.',
         'test conditions': 'The inputs and environment used during a check.'}),
    76: _item(
        'Help someone else run and understand the project',
        'A README is the main written introduction to a code project. It should explain what the app does, how to start it, and what it cannot yet do. Setup instructions need enough detail for someone who does not have your machine.',
        'Your notes assistant guide lists the required language version, installation step, example settings, start command and test command. '
        'It uses placeholder values for private keys. '
        'The demo section gives one sample note and question, and the limitations explain unsupported files and answers without evidence.',
        ['Write the shortest repeatable setup path.', 'Use an example settings file without real secrets.',
         'Try the guide from a clean setup and fix missing steps.'],
        'Should a setup guide include your real private service key so another person can run faster?',
        'No. Explain how they provide their own permitted key or use a local demonstration mode.',
        {'README': 'A project’s introductory instruction file.', 'placeholder': 'An example value that must be replaced.',
         'clean setup': 'Starting without relying on your existing installed or saved state.'}),
    77: _item(
        'Walk through the complete project clearly',
        'A project walkthrough tells a connected story from user problem to working result. Show the main journey first. Then explain the important parts and one measured limitation using the same example.',
        'Begin with A learner wants answers from their notes. Upload the Friday exam note and show the question, answer and source. '
        'Next, explain that the page sends the question, the server checks permission, and search finds the relevant text. '
        'Finish by showing a missing classroom question that the assistant correctly cannot answer.',
        ['State the user problem in one sentence.', 'Demonstrate one complete journey.',
         'Explain the result path and one real limitation.'],
        'Choose a single example that connects the demo to the explanation.',
        'Use the exam-date question throughout. It lets the listener follow the same input through saving, search, answering and citation.',
        {'walkthrough': 'A guided explanation of how something works.', 'architecture': 'How the main parts of a system fit together.',
         'limitation': 'Something the current project cannot reliably handle.'}),
    78: _item(
        'Explain page state and keyboard access',
        'Page state describes what the interface currently remembers. Clear state changes help users know whether work is waiting, finished or failed. Accessibility makes those changes and controls usable by people with different needs.',
        'A question page starts ready, becomes loading after Send, then shows either an answer or an error. '
        'The question remains available after an error. A keyboard user can reach Send, see the focused control, and hear the result status through appropriate page announcements. '
        'Colour alone should not be the only sign of failure.',
        ['Name the states of one page action.', 'Explain the visible change for each state.',
         'Try the action without a mouse.'],
        'Explain why a red border alone is a weak error message.',
        'It does not say what went wrong or how to fix it, and some people may not perceive the colour. Add clear text tied to the input.',
        {'state': 'Information the page currently remembers.', 'accessibility': 'Making a product usable by people with different abilities.',
         'focus': 'The control currently receiving keyboard input.'}),
    79: _item(
        'Explain a protected request from page to database',
        'A clear interview answer follows one real request through the app. Authentication establishes who is asking. Authorization decides whether that person may access the record, and the database provides the permitted saved information.',
        'Asha opens note 8. The page sends the request with its protected sign-in cookie. '
        'The server checks the session, checks that Asha may read note 8, then queries the database. '
        'It returns the permitted note or an appropriate error. The page never needs the database password.',
        ['Identify the requested action and record.', 'Explain identity and permission checks in order.',
         'Describe the database read and the returned result.'],
        'Where should the check for note ownership happen?',
        'On the server before returning the note. Hiding a link in the browser does not prevent a direct request.',
        {'authentication': 'Checking who the caller is.', 'authorization': 'Checking what that caller may do.',
         'query': 'A request to read or change database information.'}),
    80: _item(
        'Find which part makes a feature slow',
        'Debugging starts with observing the problem. Split a slow request into parts and measure them before choosing a fix. Changing the part that already takes little time may barely improve the whole journey.',
        'A search takes five seconds: four seconds reading the database, half a second preparing the answer, and half a second sending and displaying it. '
        'The database read is the largest part. '
        'Check its query, selected rows and useful indexes first. Making a button animation faster will not remove the four-second database delay.',
        ['Repeat the slow action with known input.', 'Measure the time spent in its main steps.',
         'Change the largest relevant cause and measure again.'],
        'If the database time falls from four seconds to one while other parts stay the same, what is the new total?',
        'Two seconds: one for the database plus the two half-second parts.',
        {'debugging': 'Finding and fixing the cause of a problem.', 'bottleneck': 'The part that most limits overall speed.',
         'measurement': 'A recorded observation rather than a guess.'}),
    81: _item(
        'Explain why you chose particular checks',
        'An interview explanation should connect a test to the mistake it catches. Delivery checks decide whether a change is ready to release. Explain what the checks cover and what still needs observation after release.',
        'A unit test checks that minutes add correctly. An API test checks that a save reaches the database. '
        'A browser test checks that a learner can complete the visible journey. '
        'Automatic release checks run these important tests, while monitoring watches real failures after deployment. Each check answers a different question.',
        ['Name one important failure you want to prevent.', 'Choose the smallest useful test that catches it.',
         'Explain the extra checks needed before and after release.'],
        'Which test best checks that a user can reach the Save button with a keyboard?',
        'A page or browser interaction check. A calculation unit test cannot show whether a real control can receive keyboard focus.',
        {'unit test': 'A check of a small piece of code.', 'browser test': 'A check that interacts with the page.',
         'delivery': 'The process of preparing and releasing a change.'}),
    82: _item(
        'Review how the project’s parts fit together',
        'A code review looks for correctness, clarity and missing checks. Start with one user action instead of reading unrelated files at random. Follow its information through each part and ask what happens when a step fails.',
        'Review a private document upload. The page sends a file; the server checks sign-in, permission, size and content. '
        'Storage keeps the file, and the database records its owner. '
        'If the database save fails after file storage succeeds, the design needs cleanup or a recorded recovery task so an untracked file is not left forever.',
        ['Choose one important action to trace.', 'Check validation and permissions along that path.',
         'Find what happens after each possible failure.'],
        'What question should you ask when one action writes to both file storage and a database?',
        'What happens if one write succeeds and the other fails? Look for a deliberate cleanup or recovery plan.',
        {'code review': 'Examining code to find problems and improve understanding.',
         'architecture': 'How the main parts work together.', 'recovery': 'Getting back to a valid state after failure.'}),
    83: _item(
        'Tell a project story using real evidence',
        'A useful interview story explains a situation, your responsibility, your action and the result. Keep your own contribution clear. Use real observations and give teammates credit for their work.',
        'Example practice story: Our search page felt slow. I measured the request and found repeated database reads. '
        'I changed the query and added a regression test. In the same local test, the request fell from five seconds to two. '
        'For your interview, replace this example with your actual work and measured result; do not present invented numbers as your experience.',
        ['Choose one real problem you helped solve.', 'Explain what you personally did and why.',
         'State the observed result and one lesson learned.'],
        'Replace the vague sentence I improved performance with a more useful sentence structure.',
        'I measured [specific slow step], changed [specific cause], and observed [real result] under [test conditions]. Fill the blanks with truthful details.',
        {'regression test': 'A check that stops a fixed bug from returning unnoticed.',
         'contribution': 'The part of the work you did.', 'evidence': 'An observation that supports your statement.'}),
    84: _item(
        'Make the project easy for a reviewer to understand',
        'A portfolio should help someone quickly understand the problem, your contribution and the evidence that the project works. Working links and clear setup instructions matter. Show the current project honestly, including its limits.',
        'Your project card says Private notes assistant, links to a demo and code, and names its main journey. '
        'The README provides a safe sample note and question. '
        'A short walkthrough shows a correct cited answer and a missing-information case. If the live service needs sign-in, explain the permitted demonstration route.',
        ['Open every public project link as a new visitor.', 'Check that the first description explains the user problem.',
         'Match screenshots and claims to the current version.'],
        'What should you do if a portfolio screenshot shows a feature that no longer works?',
        'Update the screenshot or clearly explain its status. A reviewer should be able to connect the claim to a current working feature.',
        {'portfolio': 'A collection showing your work.', 'reviewer': 'Someone examining the project.',
         'walkthrough': 'A guided demonstration and explanation.'}),
    85: _item(
        'Review values, page actions and requests together',
        'Basic programming, browser behaviour and API requests meet in one ordinary action. A value starts in an input, a function checks it, and a request sends it to the server. Explain the same example from beginning to end.',
        'A learner types 20 into Study minutes and presses Save. The page reads the input and sends {"minutes": 20}. '
        'The server checks that 20 is allowed, saves it, and returns the saved session. '
        'The page changes from Saving to Saved. If the server rejects the input, it shows the reason instead.',
        ['Name the input value and the button event.', 'Write the request and expected response in plain words.',
         'Explain success and failure displays.'],
        'In this journey, what is the difference between the input value and the event?',
        '20 is information to use. Pressing Save is the event that starts the action using that information.',
        {'value': 'A piece of information.', 'event': 'A signal that something happened.',
         'API': 'An agreed way for programs to request information or work.'}),
    86: _item(
        'Review storage, permissions and tests with one record',
        'A saved record needs a clear identity and owner. Every protected operation should check the caller’s permission. Tests can prove that allowed actions work and refused actions leave the record unchanged.',
        'Session 7 belongs to Asha and contains 20 minutes. Asha changes it to 25; the server permits and saves the change. '
        'Ravi then requests deletion of session 7. The server refuses it. '
        'A test reads the record afterwards and confirms that it still belongs to Asha and still contains 25 minutes.',
        ['Identify the record and its owner.', 'Test a permitted update.',
         'Test a forbidden change and inspect the remaining data.'],
        'Why should a permission test inspect the database as well as the error reply?',
        'A broken implementation might change data and then return an error. Checking the saved record verifies that the forbidden action had no effect.',
        {'record': 'One saved item of information.', 'permission': 'The right to perform a particular action.',
         'assertion': 'A test statement that checks an expected result.'}),
    87: _item(
        'Diagnose a bug and explain a small fix',
        'A good debugging explanation starts with expected and observed behaviour. Use a small example that reliably shows the difference. After fixing the cause, check both that example and one nearby case.',
        'The dashboard should add 20 and 10 to make 30, but shows 2010. Inspection reveals that both values arrived as text. '
        'The program joined them instead of adding numbers. '
        'Validate and convert accepted numeric input at the boundary, then test 20 plus 10 and an invalid value such as hello.',
        ['State the expected result and the wrong result.', 'Find the smallest input that reproduces the issue.',
         'Fix the cause and test valid and invalid values.'],
        'Why is simply replacing the displayed text 2010 with 30 a poor fix?',
        'It hides one symptom without correcting the calculation. Other inputs would still be joined as text and produce wrong totals.',
        {'reproduce': 'Make the same problem happen again reliably.', 'boundary': 'The place where outside information enters the program.',
         'root cause': 'The underlying reason the mistake happens.'}),
    88: _item(
        'Present the project in five minutes',
        'A short presentation needs a clear path through the most useful evidence. Start with the problem and show the working journey. Spend the remaining time explaining one design choice, one check and one limitation.',
        'Use minute 1 for the learner’s problem, minute 2 for the notes-to-answer demo, and minute 3 for the page-server-search path. '
        'Use minute 4 for permission and answer-quality checks. '
        'Use minute 5 for a measured limitation and the next improvement. Practise aloud so the demonstration leaves time for explanation.',
        ['Choose one demonstration input in advance.', 'Practise the five parts with a timer.',
         'Remove details that do not support the main journey.'],
        'Which is a stronger limitation statement: AI can be wrong, or a specific failed example?',
        'A specific example is stronger: The assistant missed the date when it appeared only in an unsupported scanned page. Explain how you checked that failure.',
        {'design choice': 'A decision about how the system works.', 'limitation': 'A known boundary of what the project can do.',
         'evidence': 'An observed result supporting a claim.'}),
    89: _item(
        'Check the project from a new visitor’s view',
        'A project can work on your machine while missing steps for someone else. A fresh setup checks whether the written guide is complete. Public links also need to work without relying on your private browser session.',
        'Open the portfolio link in a fresh browser visit. Follow the code link and setup guide using the documented versions and example settings. '
        'Run the sample question and the stated tests. '
        'If the guide forgets a required setting, add its name and safe instructions instead of supplying your private value.',
        ['Check demo, code and documentation links.', 'Follow the setup instructions from the beginning.',
         'Record and repair each missing step.'],
        'A demo works only while you are signed in as its owner. What needs clarification?',
        'How an intended reviewer can access a permitted demo. Provide a supported sign-in or demonstration path without exposing your private account.',
        {'fresh setup': 'Starting without your existing local state.', 'documentation': 'Written instructions and explanations.',
         'reviewer': 'The person evaluating your work.'}),
    90: _item(
        'Finish with evidence and a focused next-step plan',
        'The final demo should show what you can explain and do today. Use the course work to identify specific strengths and gaps. Completing 90 days is practice evidence, not a guarantee of a job or mastery of every topic.',
        'Demonstrate the notes assistant, trace one request, and explain a permission failure. '
        'Then review your practice notes: perhaps requests are clear but indexes are difficult. '
        'Compare a database search before and after an index, and practise explaining the measured result.',
        ['Run the final project journey and its important checks.', 'Explain one design choice and one known failure.',
         'Choose the next practice task from an observed weakness.'],
        'Write one useful next-step goal after struggling to explain database indexes.',
        'Compare one learner-session query with and without an index, record the search plan, and explain the result in simple words. This is more actionable than Learn everything again.',
        {'practice evidence': 'Work or observations showing a skill you used.', 'gap': 'A specific skill that still needs work.',
         'actionable goal': 'A goal with a clear next action and way to check completion.'}),
}


def lesson(day: int) -> dict:
    """Return an independent copy of the numbered full-stack lesson."""
    if type(day) is not int or not 1 <= day <= 90:
        raise ValueError('Choose a course day from 1 to 90.')
    return deepcopy(_LESSONS[day])
