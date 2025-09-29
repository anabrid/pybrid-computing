from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np
import copy

luci    = LUCIDAC()

circuits = list()

N   = 4

x   = []
m   = []

l   = Circuit()                         # Create a circuit

for i in range(N):
    x.append(l.int())
    m.append(l.mul())

for i in range(N):
    l.connect(x[i-1], m[i].a, weight=-1.)

    l.connect(x[i-2], m[i].b, weight=+1.)
    l.connect(x[i-3], m[i].b, weight=-1.)

    l.connect(m[i], x[i], weight=-6.66)
    l.connect(m[i], x[i], weight=-6.66)
    l.connect(m[i], x[i], weight=-6.66)
    l.connect(x[i], x[i], weight=+1.)
    l.measure(x[i], adc_channel=i)

F = l.const()
F_values = np.arange(0.0, 1.00, 0.01)
for F_value in F_values:
    l_ = copy.deepcopy(l)
    for i in range(N):
        l_.connect(F, x[i], weight=-F_value)
    luci.set_circuit(l_)
    luci.set_circuit(l_)
    luci.set_circuit(l_)
    luci.set_circuit(l_)
    luci.set_circuit(l_)
    luci.set_circuit(l_)
    luci.set_circuit(l_)
    luci.set_circuit(l_)
    luci.set_circuit(l_)
    luci.set_circuit(l_)


op_secs     = .1                        # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second

luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

runs = luci.run()



n = len(runs) // F_values.shape[0]
data = {F_value: [np.array(list(runs[n*i+j].data.values())) for j in range(n)] for i, F_value in enumerate(F_values)}
ratios = {}


ax = plt.figure(figsize=(8,8), dpi=300).add_subplot()

for F_value, run_datas in data.items():
    filename = f"lorenz96/data-{F_value:.04f}"
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_ylim(-1., +1.)
    ax.set_xlim(-1., +1.)
    ratio = []
    for i, run_data in enumerate(run_datas):
        np.savetxt(filename+f"_{i:02.0f}.csv", run_data.T, delimiter=",")
        ax.plot(-run_data[0], -run_data[1], ls="-", lw=0.5, label=f"run {i:02.0f}")
        d0 = np.sqrt(np.sum((run_datas[i][:, 0] - run_datas[i-1][:, 0])**2))
        d1 = np.sqrt(np.sum((run_datas[i][:,-1] - run_datas[i-1][:,-1])**2))
        ratio.append(d1/d0)
    ratios[F_value] = np.mean(np.array(ratio))
    ax.set_title(filename)
    ax.legend()
    plt.savefig(filename+".png")
    plt.cla()
    print(f"{filename} has been saved.", end="\r")
plt.close()

ax = plt.figure(figsize=(8,8), dpi=300).add_subplot()
ax.plot(ratios.keys(), ratios.values())
ax.set_yscale("log")
plt.savefig("ratios.png")
plt.show()

"""
works
"""