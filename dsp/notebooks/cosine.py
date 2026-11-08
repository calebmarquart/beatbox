# %% [markdown]
# # Cosine test
#
# Sanity check that the environment works.

# %%
import matplotlib.pyplot as plt
import numpy as np

fs = 100.0  # sample rate, Hz
f = 1.0  # cosine frequency, Hz
t = np.arange(0, 5, 1 / fs)
x = np.cos(2 * np.pi * f * t)

fig, ax = plt.subplots(figsize=(10, 3))
ax.plot(t, x)
ax.set_xlabel("Time (s)")
ax.set_ylabel("Amplitude")
ax.set_title(f"cos(2π·{f}·t), fs = {fs} Hz")
ax.grid(True)
plt.show()
