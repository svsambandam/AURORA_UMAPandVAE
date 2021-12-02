# EXPLORING DISTRIBUTION DRIVEN LATENT SPACES FOR QUALITY DIVERSITY | Expanding upon AURORA
Work done for term project for Jeff Clune's 532J Course on Never-ending RL

Rrobots benefit from learning a large set of diverse behaviours; but the task of defining a good behavior descriptor requires prior knowledge of the specific task and some good engineering. Dr. Antoine Cully proposes AURORA that mitigiates this pitfall by combinng dimensionality reduction and quality diversity algorithms, to handle the specific problem of autonomous learning. This universal algorithm for robotic skill discovery is done without user input. This paper leverages PCA and autoencoders to project sensory data into low dimensional space that can be explored using evolutionary algorithms. This project is an extension to that work by exploring dimensionality reduction algorithms  that encourage the latent representations to follow specific distributions, namely Gaussian using VAE and Reimannian using UMAP.


This work is based off of the original research done in 2019 by Dr Antoine Cully from "Autonomous skill discovery with Quality-Diversity and Unsupervised Descriptors" ( https://arxiv.org/abs/1905.11874)

This repo contains my implementation of AURORA variants that contain PCA, VAE, and UMAP; This code builds upon a python re-implementaion of AURORA for autoencoders and genotype that can be found here (https://github.com/Kyzarok/MScProject_AURORA_with_RNN/).


SETTING UP THE ENVIRONMENTS
Running the main code requires you to run in different conda environments depending on the version run:
  When running PCA and UMAP which uses CuML:  conda env create -f environment_pca_umap.yml 
  "**conda activate aurora-pca-umap**"
  
  When running AE and VAE which uses tensorflow v1:  conda env create -f environment_ae_vae.yml 
  "**conda activate aurora-ae-vae**"
  
  When running ground truth or genotype, you can use either environment
  

RUNNING EXPERIMENTS
You can run this code with the command "**$python3 main_aurora.py**". This command line can take multiple arguments:

--version : A string that defines which algorithm to run. The default is "null". Can take as argument:
"GT" to generate a reference ground truth distribution
"genotype" to run the genotype method
"pretrainedPCA" to run the pretrained version of AURORA-PCA
"incrementalPCA" to run the incremental version of AURORA-PCA
"pretrainedAE" to run the pretrained version of AURORA-AE
"incrementalAE" to run the incremental version of AURORA-AE
"pretrainedVAE" to run the pretrained version of AURORA-VAE
"incrementalVAE" to run the incremental version of AURORA-VAE
"pretrainedUMAP" to run the pretrained version of AURORA-UMAP
"incrementalUMAP" to run the incremental version of AURORA-UMAP
--plot_runs : An int that will choose whether to plot metrics. If you have run all of the variations, enter "1". The default is "0".
--num_epochs : An int that sets the number of epochs that will be used to train the VAEs and AEs in the AE versions. The default is "500".

Note, that re-running code will overwrite whatever plots and data is currenlty inside the RUN_DATA folder.

Be sure to run "**$python3 main_aurora.py --version GT**" first as all other versions require a ground truth latent space to project onto
