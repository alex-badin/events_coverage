-- The counting behind event_group_terms groups on term_hash, a number computed from the term.
-- Two terms with the same number would be added together with no error anywhere, so this checks
-- that the number stands for exactly one term.

select term_hash
from {{ ref('int_post_term_forms') }}
group by term_hash
having min(term_type || ' ' || term_key) != max(term_type || ' ' || term_key)
