{% test rank_in_window(model, column_name) %}
-- Fails for any row where the rank falls outside the 1..100 window we snapshot.
select * from {{ model }} where {{ column_name }} < 1 or {{ column_name }} > 100
{% endtest %}
