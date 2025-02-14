"""
author: rohan singh
this python script will be used to query the data for the features defined in the README that we will be using in our forecast model.
"""

# imports
import pandas_gbq as pdgbq
import pandas as pd

project_id = 'tr-live-demo'
model_date = '2025-02-13'

query = f'''
WITH interval_midpoints AS (
    SELECT 
        RIC, 
        ((EXTRACT(HOUR FROM Time) + CAST(GMT_Offset AS INT64)) * 360 +
         EXTRACT(MINUTE FROM Time) * 6 +
         CAST(FLOOR(EXTRACT(SECOND FROM Time)/10.0) AS INT64)) AS interval_seqno,
        ROUND(AVG(Bid_Price + Ask_Price)/2.0, 2) AS avg_mid
    FROM `tr-ems-integration.PE62.tickdb`
    WHERE _PARTITIONDATE = '{model_date}'
        AND Type = 'Quote' AND Bid_Price > 0 AND Ask_Price > 0
    GROUP BY _PARTITIONDATE, RIC, interval_seqno
),
trailing_midpoints AS (
    SELECT RIC, interval_seqno,
        ARRAY_AGG(avg_mid) OVER (
            PARTITION BY RIC
            ORDER BY interval_seqno
            RANGE BETWEEN 120 PRECEDING AND 0 FOLLOWING
        ) AS trailing_mids
    FROM interval_midpoints
    GROUP BY RIC, interval_seqno, avg_mid
),
avg_daily_volumes AS (
    SELECT RIC,
        SUM(Volume)/COUNT(DISTINCT CAST(Time AS DATE)) AS daily_volume
    FROM `tr-ems-integration.PE62.tickdb`
    WHERE _PARTITION BETWEEN '{model_date}' - INTERVAL 28 DAY AND '{model_date}'
        AND Volume > 0 AND Type = 'Trade'
    GROUP BY RIC
),
interval_volumes AS (
    SELECT RIC, 
        ((EXTRACT(HOUR FROM Time) + CAST(GMT_Offset AS INT64)) * 360 +
         EXTRACT(MINUTE FROM Time) * 6 +
         CAST(FLOOR(EXTRACT(SECOND FROM Time)/10.0) AS INT64)) AS interval_seqno,
        CAST(SUM(Volume) AS FLOAT64) * 10000.0 / AVG(adv.daily_volume) AS sum_volume_as_bps_avg_volume
    FROM `tr-ems-integration.PE62.tickdb` tickdb
    JOIN avg_daily_volumes adv USING(RIC)
    WHERE _PARTITIONDATE = '{model_date}' AND Type = 'Trade'
    GROUP BY _PARTITIONDATE, RIC, interval_seqno
    HAVING sum_volume_as_bps_avg_volume > 0
),
sum_interval_volumes AS (
    SELECT RIC, interval_seqno,
        SUM(sum_volume_as_bps_avg_volume) OVER (
            PARTITION BY RIC
            ORDER BY interval_seqno
            RANGE BETWEEN 120 PRECEDING AND 0 FOLLOWING
        ) AS sum_interval_volumes
    FROM interval_volumes
    GROUP BY RIC, interval_seqno, sum_volume_as_bps_avg_volume
)
SELECT * FROM trailing_midpoints
JOIN sum_interval_volumes USING (RIC, interval_seqno)
'''

trailing_midpoints_df = pdgbq.read_gbq(
    query, project_id=project_id, dialect='standard'
)
