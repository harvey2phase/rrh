import os
import datetime

def mkdir(path):
    if os.path.exists(path):
        print("Directory %s already exists!" % path)
    else:
        try:
            os.mkdir(path)
        except OSError:
            print("Creation of the directory %s failed" % path)
        else:
            print("Successfully created the directory %s " % path)

MY_DRIVE = "/home/harveyw/projects/def-ttt/harveyw"
RESULTS = os.path.join(MY_DRIVE, "rrh-MNIST-results/no_bn")

RESULTS_FOLDER = os.path.join(
    RESULTS, datetime.datetime.now().strftime("%m-%d_%H-%M"),
)
mkdir(RESULTS_FOLDER)

import seaborn as sns
sns.set()


import urllib
import numpy as np
import matplotlib.pyplot as plt

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.utils
import torchvision.transforms as transforms

from torch.utils.data import DataLoader
from torchvision.datasets import MNIST
from torch.optim.lr_scheduler import StepLR

GPU = True
device = torch.device("cuda:0" if GPU and torch.cuda.is_available() else "cpu")

"""## Debugging Tools"""

def plot(x, x_recon, kind):
    count = 0
    if kind == "train":
        recon_c = "red"
    else:
        recon_c = "green"
    for i in range(1):
        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.scatter(np.linspace(0, 127, 128), x.detach().cpu()[i], c = "blue")
        ax.scatter(np.linspace(0, 127, 128), x_recon.detach().cpu()[i], c = recon_c)
        #plt.show()
        plt.savefig(os.path.join(RESULTS_FOLDER, "training_curve.png"), dpi = 600)

"""# Load MNIST"""

BATCH_SIZE = 64

def load_mnist(train, batch_size = BATCH_SIZE):
    img_transform = transforms.Compose([
        transforms.ToTensor(),
        #transforms.Normalize((0.1307,), (0.3081,)),
    ])

    return DataLoader(
        dataset = MNIST(
            root = './data/MNIST',
            download = True,
            train = train,
            transform = img_transform,
        ),
        batch_size = batch_size,
        shuffle = train,
        drop_last = train,
    )

def to_numpy_arrays(dataloader):
    data = list(dataloader)
    data = [[sample[0].numpy(), sample[1].numpy()] for sample in data]
    X = np.vstack([sample[0] for sample in data])
    y = np.hstack([sample[1] for sample in data])
    return X, y

train_dataloader = load_mnist(True)
test_dataloader = load_mnist(False)

TEST_LEN = len(test_dataloader.dataset)

train_X, train_y = to_numpy_arrays(train_dataloader)
test_X, test_y = to_numpy_arrays(test_dataloader)

"""# Model Definitions"""

def freeze(model):
    for param in model.parameters():
        param.requires_grad = False

"""## CNN"""

CNN_EPOCH = 14
LR = 1.0
GAMMA = 0.7
LOG_INT = 10


"""## VAE"""

LAT_DIM = 2
OBS_DIM = 128
CAPACITY1 = 128 * 2 ** 5
CAPACITY2 = 64 * 2 ** 5
LRN_RATE = 1e-3
WEIGHT_DECAY = 1e-5
VAR_BETA = 1
VAE_EPOCH = 10
#DROPOUT_PROB = 0.5

class Encoder(nn.Module):
    def __init__(self):
        super(Encoder, self).__init__()

        self.hidden1 = nn.Linear(
            in_features = OBS_DIM,
            out_features = CAPACITY1,
        )

        self.hidden2 = nn.Linear(
            in_features = CAPACITY1,
            out_features = CAPACITY2,
        )

        self.bn1 = nn.BatchNorm1d(CAPACITY1)
        self.bn2 = nn.BatchNorm1d(CAPACITY2)

        self.fc_mu = nn.Linear(
            in_features = CAPACITY2,
            out_features = LAT_DIM,
        )
        self.fc_logvar = nn.Linear(
            in_features = CAPACITY2,
            out_features = LAT_DIM,
        )

    def forward(self, x):
        x = self.hidden1(x)
        #x = self.bn1(x)
        x = F.relu(x)

        x = self.hidden2(x)
        #x = self.bn2(x)
        x = F.relu(x)

        x_mu = self.fc_mu(x)
        x_logvar = self.fc_logvar(x)
        return x_mu, x_logvar

class Decoder(nn.Module):
    def __init__(self):
        super(Decoder, self).__init__()

        self.hidden1 = nn.Linear(
            in_features = LAT_DIM,
            out_features = CAPACITY2,
        )
        self.hidden2 = nn.Linear(
            in_features = CAPACITY2,
            out_features = CAPACITY1,
        )

        self.bn1 = nn.BatchNorm1d(CAPACITY2)
        self.bn2 = nn.BatchNorm1d(CAPACITY1)

        self.output = nn.Linear(
            in_features = CAPACITY1,
            out_features = OBS_DIM,
        )

    def forward(self, x):
        x = self.hidden1(x)
        #x = self.bn1(x)
        x = F.relu(x)

        x = self.hidden2(x)
        #x = self.bn2(x)
        x = F.relu(x)

        x = self.output(x)
        x = x.view(x.size(0), OBS_DIM)
        return x

class VariationalAutoencoder(nn.Module):
    def __init__(self):
        super(VariationalAutoencoder, self).__init__()

        self.encoder = Encoder()
        self.decoder = Decoder()

    def forward(self, x):
        latent_mu, latent_logvar = self.encoder(x)
        latent = self.latent_sample(latent_mu, latent_logvar)
        x_recon = self.decoder(latent)
        return x_recon, latent_mu, latent_logvar

    def latent_sample(self, mu, logvar):
        if self.training:
            # the reparameterization trick
            std = logvar.mul(0.5).exp_()
            eps = torch.empty_like(std).normal_()
            return eps.mul(std).add_(mu)
        else:
            return mu

def reconstruction_error(recon_x, x):
    return F.mse_loss(
        recon_x.view(-1, OBS_DIM),
        x.view(-1, OBS_DIM),
        reduction = "sum",
    )

def vae_loss(recon_loss, mu, logvar):
    kl_divergence = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())
    return recon_loss + VAR_BETA * kl_divergence

"""### Training and Evaluation


"""

def train_vae(vae, optimizer, evaluate = True):

    vae.train()

    num_params = sum(p.numel() for p in vae.parameters() if p.requires_grad)
    print('Number of parameters: %d' % num_params)

    if evaluate:
        train_loss, train_recon_loss = [], []
        test_train_loss, test_train_recon_loss = [], []
        test_eval_loss, test_eval_recon_loss = [], []

    print("Training: ", end = "")
    for epoch in range(VAE_EPOCH):
        if evaluate:
            train_loss.append(0)
            train_recon_loss.append(0)
            image_count = 0

        for image_batch, _ in train_dataloader:

            image_batch = image_batch.to(device)
            image_batch = cnn.penultimate_layers(image_batch)

            image_batch_recon, latent_mu, latent_logvar = vae(image_batch)
            #plot(image_batch, image_batch_recon, kind = "train")

            recon_loss = reconstruction_error(image_batch_recon, image_batch)
            loss = vae_loss(recon_loss, latent_mu, latent_logvar)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            if evaluate:
                train_loss[-1] += loss.item()
                train_recon_loss[-1] += recon_loss

                image_count += len(image_batch)

        if evaluate:
            vae.train()
            train_loss[-1] /= image_count
            train_recon_loss[-1] /= image_count

            vae.train()
            recon_loss_avg, loss_avg = eval_vae(vae)
            test_train_loss.append(loss_avg)
            test_train_recon_loss.append(recon_loss_avg)

            vae.eval()
            recon_loss_avg, loss_avg = eval_vae(vae)
            test_eval_loss.append(loss_avg)
            test_eval_recon_loss.append(recon_loss_avg)

            vae.train()

        print("%d, " % (epoch+1), end = "")

    print()
    if evaluate:
        return (
            vae, optimizer,
            [np.array(train_loss), np.array(train_recon_loss)],
            [np.array(test_train_loss), np.array(test_train_recon_loss)],
            [np.array(test_eval_loss), np.array(test_eval_recon_loss)],
        )
    return vae, optimizer

def eval_vae(vae):

    test_loss, test_recon_loss = 0, 0
    image_count = 0
    for image_batch, _ in test_dataloader:

        with torch.no_grad():

            image_batch = image_batch.to(device)
            image_batch = cnn.penultimate_layers(image_batch)

            image_batch_recon, latent_mu, latent_logvar = vae(image_batch)
            #plot(image_batch, image_batch_recon, kind = "test")

            recon_loss = reconstruction_error(image_batch_recon, image_batch)
            loss = vae_loss(recon_loss, latent_mu, latent_logvar)

            test_recon_loss += recon_loss
            test_loss += loss.item()

            image_count += len(image_batch)

    return test_recon_loss / image_count, test_loss / image_count

def plot_loss(train_losses, test_train_losses, test_eval_losses):
    plt.ion()

    plotlabels = ["Total error", "Reconstruction error", "KL divergence"]
    train_losses.append(train_losses[0] - train_losses[1])
    test_train_losses.append(test_train_losses[0] - test_train_losses[1])
    test_eval_losses.append(test_eval_losses[0] - test_eval_losses[1])

    ncols = 3
    fig, ax = plt.subplots(ncols = ncols, figsize = (9, 2.5))

    for i in range(ncols):
        ax[i].plot(train_losses[i], c = "blue", label = "training")
        ax[i].plot(test_train_losses[i], c = "green", label = "test (train)")
        ax[i].plot(test_eval_losses[i], c = "red", label = "test (eval)")

        ax[i].set_title(plotlabels[i])

    plt.tight_layout()
    plt.legend()
    #plt.show()
    plt.savefig(os.path.join(RESULTS_FOLDER, "training_curve.png"), dpi = 600)

"""### Load VAE"""

def new_vae():
    vae = VariationalAutoencoder()
    vae = vae.to(device)

    optimizer = torch.optim.Adam(
        params = vae.parameters(),
        lr = LRN_RATE,
        weight_decay = WEIGHT_DECAY,
    )
    return vae, optimizer

def load_vae(folder_name, vae_name, optimizer_name = "adam.pth"):
    folder_name = os.path.join(RESULTS, folder_name)

    vae = VariationalAutoencoder()
    vae.load_state_dict(torch.load(os.path.join(folder_name, vae_name)))
    vae.to(device)
    optimizer = torch.optim.Adam(
        params = vae.parameters(),
        lr = LRN_RATE,
        weight_decay = WEIGHT_DECAY,
    )
    optimizer.load_state_dict(torch.load(
        os.path.join(folder_name, optimizer_name)
    ))
    return vae, optimizer

"""# RRH for Gaussian Mixtures"""

def scale_to_cov(scales):
    return np.vstack([np.expand_dims(np.diagflat(s), 0) for s in scales])

def pool_covariance(means, covs):
    K = covs.shape[0]
    p = np.repeat(1/K, K)
    cov_ = np.einsum('ijk,i->jk', covs, p) + np.einsum('ij,ik,i->jk', means, means, p)
    mu_ = np.einsum('ij,i->j', means, p)
    return cov_ - np.einsum('i,j->ij', mu_, mu_)

def mvn_renyi(C, q=1):
    """ Computes the Rényi heterogeneity for a multivariate Gaussian
    Arguments:
        C: `ndarray((n,n))`. Covariance matrix
        q: `0<float`. Order of the heterogeneity
    Returns:
        `float`
    """
    n = C.shape[0]
    SqrtDetC = np.sqrt(np.linalg.det(C))
    if q == 1:
        out = (2*np.pi*np.e)**(n/2) * SqrtDetC
    elif q == np.inf:
        out = (2*np.pi)**(n/2) * SqrtDetC
    elif q!=1 and q!=0 and q!=np.inf:
        out = ((2*np.pi)**(n/2))*(q**(n/(2*(q-1))))*SqrtDetC
    return out

def mvn_renyi_alpha(C,  q=1):
    """ Computes the alpha-heterogeneity for a Gaussian mixture where each sample has equal weight

    Arguments:

        cov: `ndarray((nsamples, n, n))`. Covariance matrices
        q: `0<float`. Order of the heterogeneity metric

    Returns:

        `float`. The alpha-heterogeneity
    """
    K, n, _ = C.shape
    p = np.repeat(1/K, K)
    if q == 1:
        out = np.exp((n + np.sum(p*np.log(np.linalg.det(2*np.pi*C))))/2)
    elif q!=np.inf and q!=1 and q!=0:
        wbar = (p**q)/np.sum(p**q)
        out = ((2*np.pi)**(n/2))*np.sum(wbar*np.sqrt(np.linalg.det(C)))/(q**(n/2))**(1/(1-q))
    return out

"""## Calculation"""

def calculate_rrh(vae, X, y):
    gammas, alphas, betas = [], [], []
    for i in range(10):
        mu, logvar = vae.encoder(
            cnn.penultimate_layers(torch.Tensor(X[y == i]).to(device)),
        )
        loc = mu.cpu().detach().numpy()
        scale = logvar.exp().cpu().detach().numpy()
        cov = scale_to_cov(scale)
        gamma = mvn_renyi(pool_covariance(loc, cov), q=1)
        alpha = mvn_renyi_alpha(cov,q=1)
        beta = gamma/alpha
        gammas.append(gamma)
        alphas.append(alpha)
        betas.append(beta)
    return np.array(gammas), np.array(alphas), np.array(betas)


def het_sigma(matrix, avg = None):
    if avg == None:
        avg = het_avg(matrix)
    n = len(matrix)
    mse = (matrix[0] - avg) ** 2
    for i in range(1, n):
        mse += (matrix[i] - avg) ** 2
    return np.sqrt(mse / n)

def het_sum(matrix):
    sum = matrix[0] + matrix[1]
    for i in range(2, len(matrix)):
        sum += matrix[i]
    return sum

def het_avg(matrix):
    return het_sum(matrix) / len(matrix)

"""## Plotting"""

def plot_rrh(gammas, alphas, betas, filename, sigmas = None):
    if not (len(gammas) == len(alphas) or len(gammas) == len(betas)):
        sys.exit("Mismatched matrix size")
    n = len(gammas)
    hetvalues = [gammas, alphas, betas]
    plotlabels = [r"Pooled", r"Within-Observation", r"Between-Observation"]

    fig, ax = plt.subplots(ncols=3, figsize=(9, 2.5))
    ax[0].set_ylabel("Heterogeneity")

    for i in range(3):
        ax[i].set_title(plotlabels[i])
        ax[i].set_xticks(np.arange(10))
        ax[i].set_xticklabels(np.arange(10))
        ax[i].bar(
            np.arange(10),
            hetvalues[i],
            facecolor = plt.get_cmap("Greys")(0.4),
            edgecolor = "black",
        )
        if not sigmas == None:
            ax[i].errorbar(
                np.arange(10),
                hetvalues[i],
                yerr = sigmas[i],
                fmt = "none",
                ecolor = "r",
                capsize = 3,
                label = "std deviation",
            )
            ax[i].errorbar(
                np.arange(10),
                hetvalues[i],
                yerr = sigmas[i] / np.sqrt(n),
                fmt = "none",
                ecolor = "b",
                capsize = 3,
                label = "std error",
            )
    plt.tight_layout()
    #plt.show()
    plt.savefig(os.path.join(RESULTS_FOLDER, filename + ".png"), dpi = 600)

"""# Experiments"""

cnn = create_and_train_cnn()
#cnn = load_cnn("12-19_epoch=14.pth")
freeze(cnn)
cnn.eval()


trained_epoch = 0

#vae, optimizer = load_vae("12-20_00-24", vae_name = "vae_epoch=50.pth")
vae, optimizer = new_vae()

vae, optimizer, train_losses, test_train_losses, test_eval_losses = train_vae(
    vae, optimizer, evaluate = True,
)

torch.save(vae.state_dict(), os.path.join(
    RESULTS_FOLDER, "vae_epoch=" + str(trained_epoch + VAE_EPOCH) + ".pth"
))
torch.save(optimizer.state_dict(), os.path.join(RESULTS_FOLDER, "adam.pth"))
with open(os.path.join(RESULTS_FOLDER, "vae.txt"), "w+") as f:
    f.write(str(vae))
drive.flush_and_unmount()
drive.mount(GDRIVE)

plot_loss(train_losses, test_train_losses, test_eval_losses)

vae.train()
gammas, alphas, betas = calculate_rrh(vae, train_X, train_y)
plot_rrh(gammas, alphas, betas, filename = "het_train")

vae.eval()
gammas, alphas, betas = calculate_rrh(vae, test_X, test_y)
plot_rrh(gammas, alphas, betas, filename = "het_test")
