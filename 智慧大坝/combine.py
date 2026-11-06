import numpy as np

# 加载旧数据和新数据
old_data = np.load('training_ata.npy', allow_pickle=True)
new_data = np.load('training_ata1.npy', allow_pickle=True)

# 合并
combined = np.concatenate([old_data, new_data])

# 保存
np.save('training_data_combined.npy', combined)
print(f"旧数据: {len(old_data)}条, 新数据: {len(new_data)}条, 合并: {len(combined)}条")