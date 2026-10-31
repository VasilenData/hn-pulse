{% test unique_combination(model, combination_of_columns) %}
-- Fails for every combination of the given columns that appears more than once.
select {{ combination_of_columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ combination_of_columns | join(', ') }}
having count(*) > 1
{% endtest %}
