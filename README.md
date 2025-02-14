# personal stocks model

## model intro
this is my personal model to forecast stock returns. ive been using this model irl for my personal portfolio. this will be useful for intraday stock prediction over five-minute horizons. this model is a supervised model who's label is the actual stock return for the next five minutes.

the label that the model is trained on is defined by the log difference in prices where:  
  - $p_{start}$: 5 second average at the start.  
  - $p_{end}$: the 5 minute volume weighted average price.  
therefore, the model will be trained to predict the following label:
$$\ln(p_{end}) - \ln(p_{start})$$

## model features  

the model features that i use are extracted from thompson reuters are:  
  - intraday sequence number of the current 10-second window.
  - list of difference of logarithms of average midpoint quotes in the 120 last consecutive  10-second second intervals within the trailing 20-minute window:
  $\ln(p_{k+1}) - \ln(p_{k})$
  - logarithm of the average midpoint quote in the 10-second interval: $\ln(p_{start})$  
  - traded volume in the trailing 20-minute window normalized as a fraction of the trailing 4-week average daily volume.  
  - security identifier

## bigquery for model features
to get the model features for our model we will be using bigquery  (google sql).  

### feature 1: intraday sequence number
bigquery query to get the intraday sequence number:
```
((EXTRACT(HOUR FROM Time) + 
  CAST(GMT_Offset AS INT64)) * 360 +
  EXTRACT(MINUTE FROM Time) * 6 +
  CAST(FLOOR(EXTRACT(SECOND FROM Time)/10.0) AS INT64)) AS
interval_seqno
```

### feature 2: interval midpoints
create the temporary table:
```
WITH interval_midpoints AS(
SELECT 
    RIC, ... AS interval_seqno,
    ROUND(AVG(Bid_Price + Ask_Price)/2.0,2) AS avg_mid
FROM
    `tr-ems-integration.PE62.tickdb` tickdb
WHERE tickdb._PARTITIONDATE = '{model_date}'
AND tickdb.Type = 'Quote' AND Bid_Price > 0 AND Ask_Price > 0
GROUP BY tickdb._PARTITIONDATE, RIC, interval_seqno)
```
we will then use this temporary table within another query
```
WITH interval_midpoints AS (...)
SELECT RIC, interval_seqno,
    ARRAY_AGG(avg_mid) OVER (
        PARTITION BY RIC
        ORDER BY interval_seqno
        RANGE BETWEEN 120 PRECEDING AND 0 FOLLOWING
    ) AS trailing_mids
FROM interval_midpoints
GROUP BY RIC, interval_seqno, avg_mid
```

### feature 3: normalized traded volume
we will create a temporary table:
```
WITH avg_daily_volumes AS(
SELECT RIC,
    SUM(Volume)/COUNT(DISTINCT CAST(Time AS DATE)) AS daily_volume
FROM `tr-ems-integration.PE62.tickdb`
WHERE _PARTITION BETWEEN
    '{avg_volume_period_start}' AND '{avg_volume_period_end}'
    AND Volume > 0 AND Type = 'Trade'
GROUP BY RIC )
```
we will then use this to create another temporary table for average daily volumes:
```
WITH interval_volumes AS(
WITH avg_daily_volumes AS(...)
SELECT RIC, ... AS interval_seqno,
    CAST(SUM(Volume) AS FLOAT64) * 10000.0 / AVG(adv.daily_volume)
    AS sum_volume_as_bps_avg_volume
FROM `tr-ems-integration.PE62.tickdb` tickdb
JOIN  avg_daily_volumes adv USING(RIC)
WHERE 
    tockdb._PARTITIONDATE = '{model_date}' AND tickdb.Type = 'Trade'
GROUP BY tickdb._PARTITIONDATE, RIC, interval_seqno
HAVING sum_volume > 0) 
```
we will then use this temporary table for:
```
WITH interval_volumes AS (...)
SELECT_RIC, interval_seqno,
    SUM(sum_volume_as_bps_avg_volume) OVER (
        PARTITION BY RIC
        ORDER BY interval_seqno
        RANGE BETWEEN 120 PRECEEDING AND 0 FOLLOWING
    ) AS sum_interval_volumes
FROM interval_volumes
GROUP BY RIC, interval_seqno, sum_volume_as_bps_avg_volume
```

### feature 4: vwap in the 5-minute period
this will only be available during training time but not serving time:
```
WITH interval_price_volumes AS (...)
SELECT RIC, interval_seqno,
    ((SUM(sum_price_volume) OVER (
        PARTITION BY RIC ORDER BY interval_seqno
        RANGE BETWEEN 1 AND FOLLOWING 30 FOLLOWING)) /
    (SUM(sum_volume) OVER (
        PARTITION BY RIC ORDER BY interval_seqno
        RANGE BETWEEN 1 FOLLOWING AND 30 FOLLOWING)))
    AS vwap
FROM interval_price_volumes
GROUP BY RIC, interval_seqno, sum_price_volume, sum_volume
```

## model data
the model will be trained using TFRecords where each TF training example will be defined as:
```
example = tf.train.Example(features=tf.train.Features(feature={
    'delta_log_vwap_mid' : tf.train.Feature(float_list = 
    tf.train.FloatList(value=[row['delta_log_vwap_mid']])),
    'ric' : tf.train.Feature(bytes_list = 
    tf.train.BytesList(value=[row['RIC'].encode("utf-8")])),
    'interval_seqno' : tf.train.Feature(int64_list = 
    tf.train.Int64List(value=[row['interval_seqno']])),
    'delta_log_mids' : tf.train.Feature(float_list = 
    tf.train.FloatList(value=[row['delta_log_mids']])),
    'sum_interval_volumes' : tf.train.Feature(float_list = 
    tf.train.FloatList(value=[row['sum_interval_volumes']])),
    'log_current_mid' : tf.train.Feature(float_list = 
    tf.train.FloatList(value=[row['log_current_mid']])),
}))
```