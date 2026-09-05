# Learning memory

Each accepted study guide stores its own concepts and extracted examples. A concept
with the same name in another guide does not move or overwrite earlier guide content.
Re-importing the same guide merges examples without duplicating them.

Every checked practice attempt records correctness, answer verification, help used,
and any likely misconception. Mastery combines accuracy, amount of practice, and
independence. Revealing a solution supplies no independent evidence. Two independent
correct answers in succession resolve existing misconception flags.

Sensei checks unseen concepts first, then targets gaps, due reviews, and concepts
with weaker mastery evidence. Lessons receive this evidence and class material.
Completing a lesson does not change mastery; a fresh practice question checks what
can now be applied independently.

The schema in `sensei/schema.sql` starts empty. There is no skill catalog, XP, rank,
legacy migration chain, or terminal session extractor. New learning data is stored
in `data/study.db` and errors in `data/logs/study-errors.jsonl`.
