import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision
import sys
sys.path.append('.')
import SpikingFlow.softbp as softbp
import SpikingFlow.softbp.neuron as neuron
from torch.utils.tensorboard import SummaryWriter
import readline

# online学习的cifar10，同时去掉了编码器，直接将图像送入网络
class Net(nn.Module):
    def __init__(self, tau=100.0, v_threshold=1.0, v_reset=0.0):
        super().__init__()
        # 网络结构，卷积-卷积-最大池化堆叠，最后接一个全连接层
        self.conv = nn.Sequential(
            nn.Conv2d(3, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            neuron.LIFNode(tau=tau, v_threshold=v_threshold, v_reset=v_reset),
            nn.Conv2d(256, 256, kernel_size=3, padding=1),
            nn.MaxPool2d(2, 2),
            nn.BatchNorm2d(256),
            neuron.LIFNode(tau=tau, v_threshold=v_threshold, v_reset=v_reset),  # 16 * 16

            nn.Conv2d(256, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            neuron.LIFNode(tau=tau, v_threshold=v_threshold, v_reset=v_reset),
            nn.Conv2d(256, 256, kernel_size=3, padding=1),
            nn.MaxPool2d(2, 2),
            nn.BatchNorm2d(256),
            neuron.LIFNode(tau=tau, v_threshold=v_threshold, v_reset=v_reset),  # 8 * 8

            nn.Conv2d(256, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            neuron.LIFNode(tau=tau, v_threshold=v_threshold, v_reset=v_reset),
            nn.Conv2d(256, 256, kernel_size=3, padding=1),
            nn.MaxPool2d(2, 2),
            nn.BatchNorm2d(256),
            neuron.LIFNode(tau=tau, v_threshold=v_threshold, v_reset=v_reset),  # 4 * 4

        )
        self.fc = nn.Sequential(
            nn.Flatten(),
            nn.Linear(256 * 4 * 4, 10, bias=False),
            neuron.LIFNode(tau=tau, v_threshold=v_threshold, v_reset=v_reset)
                                )

    def forward(self, x):
        return self.fc(self.conv(x))

    def reset_(self):
        for item in self.modules():
            if hasattr(item, 'reset'):
                item.reset()
def main():
    device = input('输入运行的设备，例如“cpu”或“cuda:0”  ')
    dataset_dir = input('输入保存CIFAR10数据集的位置，例如“./”  ')
    batch_size = int(input('输入batch_size，例如“64”  '))
    learning_rate = float(input('输入学习率，例如“1e-3”  '))
    T = int(input('输入仿真时长，例如“50”  '))
    tau = float(input('输入LIF神经元的时间常数tau，例如“100.0”  '))
    train_epoch = int(input('输入训练轮数，即遍历训练集的次数，例如“100”  '))
    log_dir = input('输入保存tensorboard日志文件的位置，例如“./”  ')

    writer = SummaryWriter(log_dir)

    # 初始化数据加载器
    train_data_loader = torch.utils.data.DataLoader(
        dataset=torchvision.datasets.CIFAR10(
            root=dataset_dir,
            train=True,
            transform=torchvision.transforms.ToTensor(),
            download=True),
        batch_size=batch_size,
        shuffle=True,
        drop_last=True)
    test_data_loader = torch.utils.data.DataLoader(
        dataset=torchvision.datasets.CIFAR10(
            root=dataset_dir,
            train=False,
            transform=torchvision.transforms.ToTensor(),
            download=True),
        batch_size=batch_size,
        shuffle=True,
        drop_last=False)

    # 初始化网络
    net = Net(tau=tau).to(device)
    # 使用Adam优化器
    optimizer = torch.optim.Adam(net.parameters(), lr=learning_rate)

    train_times = 0
    for _ in range(train_epoch):
        net.train()
        for img, label in train_data_loader:
            img = img.to(device)
            label = label.to(device)

            # 运行T个时长，out_spikes_counter是shape=[batch_size, 10]的tensor
            # 记录整个仿真时长内，输出层的10个神经元的脉冲发放次数
            out_spikes_counter = 0
            for t in range(T):
                optimizer.zero_grad()

                out_spike = net(img)
                loss = F.cross_entropy(out_spike, label)
                loss.backward()
                optimizer.step()

                # 将不同时刻的网络之间的连接断开，相当于把BPTT的展开图拆分成每个时刻的子图
                for item in net.modules():
                    if isinstance(item, softbp.BaseNode):
                        item.v.detach_()

                # 只记录不含梯度的数据，节省显存/内存
                out_spikes_counter += out_spike.data


            # 重置网络的状态，因为SNN的神经元是有“记忆”的
            net.reset_()

            # 正确率的计算方法如下。认为输出层中脉冲发放频率最大的神经元的下标i是分类结果
            correct_rate = (out_spikes_counter.max(1)[1] == label.to(device)).float().mean().item()
            writer.add_scalar('train_correct_rate', correct_rate, train_times)
            if train_times % 1024 == 0:
                print(device, dataset_dir, batch_size, learning_rate, T, tau, train_epoch, log_dir)
                print(sys.argv, 'train_times', train_times, 'train_correct_rate', correct_rate)
            train_times += 1
        net.eval()
        with torch.no_grad():
            # 每遍历一次全部数据集，就在测试集上测试一次
            test_sum = 0
            correct_sum = 0
            for img, label in test_data_loader:
                img = img.to(device)
                for t in range(T):
                    if t == 0:
                        out_spikes_counter = net(img)
                    else:
                        out_spikes_counter += net(img)

                correct_sum += (out_spikes_counter.max(1)[1] == label.to(device)).float().sum().item()
                test_sum += label.numel()
                net.reset_()

            writer.add_scalar('test_correct_rate', correct_sum / test_sum, train_times)

if __name__ == '__main__':
    main()




