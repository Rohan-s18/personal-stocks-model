"""
author: rohan singh
this script will be used to generate TFRecords for the model training
"""

# import
import tensorflow as tf

tfr_file = "one_day_features_tf_records"
writer = tf.python_io.TFRecordWriter(tfr_file)

for index, row in model_features_df.iterrows():
    example = tf.train.Example(
        features=tf.train.Features(feature={...})
    )
    writer.write(example.SerializeToString())

writer.close()