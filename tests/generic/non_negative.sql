{% test non_negative(model, column_name) %}
-- Fails for any row where the value is below zero (scores and counts cannot be negative).
select * from {{ model }} where {{ column_name }} < 0
{% endtest %}
