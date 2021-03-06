import numpy as np
import individual
import random
import math
from original_ae import AE, VAE
import tensorflow.compat.v1 as tf
tf.disable_v2_behavior() 


from cuml.manifold.umap import UMAP as cuUMAP
from cuml import PCA as cuPCA
from scipy.spatial import distance

import matplotlib.pyplot as plt

from datetime import datetime
import time
start_time = time.time()

now = datetime.now()

POPULATION_INITIAL_SIZE = 200
POPULATION_LIMIT = 10000
UMAP_POPULATION_LIMIT = 5000

NUM_EPOCH = 500
BATCH_SIZE = 20000

RETRAIN_ITER = [50, 150, 350, 750, 1550, 3150]
PRINT_ITER = [0, 50, 150, 350, 750, 1550, 3150]

NB_QD_ITERATIONS = 200
NB_QD_BATCHES = 5000

MUTATION_RATE = 0.1
ETA = 10
EPSILON = 0.1

K_NEAREST_NEIGHBOURS = 2
INITIAL_NOVELTY = 0.01

FIT_MIN = 0.001
FIT_MAX = 0.999

CURIOSITY_OFFSET = 0.0000000001

FRAC = 0.0075

# Returns the decoded LSTM outputs
def translate_image(image):
    decoded = np.zeros((1, 100))
    mult = int(2/FRAC)
    for i in range(50):
        encoded = np.argmax(image[i])
        a_count = 0
        while encoded > mult:
            encoded -= ( mult + 1 )
            a_count += 1
        x = a_count
        y = encoded.copy()
        decoded[0][i] = (x * FRAC) - 1
        decoded[0][i + 50] = (y * FRAC) - 1

    return decoded

# Returns the max and min at each time step
def get_scaling_vars(population):
    dims = population[0].get_traj().shape
    max_vals = [ 0.0 for i in range(dims[0]) ] 
    min_vals = [ 99999.9 for i in range(dims[0]) ]
    for member in population:
        this_traj = member.get_traj()
        for row in range(len(this_traj)):
            get_max = np.amax(this_traj[row])
            get_min = np.amin(this_traj[row])
            if get_max > max_vals[row]:
                max_vals[row] = get_max
            if get_min < min_vals[row]:
                min_vals[row] = get_min

    max_vals = np.array(max_vals)
    min_vals = np.array(min_vals)
    return max_vals, min_vals

# Returns indices for shuffled training and validation sets
def split_dataset(pop_size):
    val_size = int(pop_size/4)
    train_size = pop_size - val_size
    indices = [ i for i in range(pop_size)]

    t_v_list = []
    for j in range(5):
        this_list = indices.copy()
        random.shuffle(this_list)
        training_indices = this_list[0 : train_size]
        val_indices = this_list[train_size : train_size + val_size]
        t_v_list.append([training_indices, val_indices])
    return t_v_list

# Returns indices for shuffles training set
def dummy_split(pop_size):
    indices = [ i for i in range(pop_size)]
    t_v_list = []
    this_list = indices.copy()
    random.shuffle(this_list)
    training_indices = this_list
    val_indices = [0 for i in range(pop_size)]
    t_v_list.append([training_indices, val_indices])
    return t_v_list

# Trains the VAE
def train_vae(prefix, vae, population, when_trained, is_pretrained, is_vae):

    _max, _min = get_scaling_vars(population)
    if is_pretrained == True:
        print("Confirmed pretrained version")

    t_loss_record = []
    v_loss_record = []
    gpu_options = tf.GPUOptions(allow_growth=True)
    with tf.Session(config=tf.ConfigProto(gpu_options=gpu_options,log_device_placement=False)) as session:
        init_all_vars_op = tf.variables_initializer(tf.global_variables(), name='init_all_vars_op')
        session.run(init_all_vars_op)
        if when_trained != 0:
            print("Loading model for retraining")
            model_name = prefix + "/MY_MODEL"
            vae.saver.restore(session, model_name)
        elif is_pretrained == False:
                if is_vae:
                    print("Training VAE, this is training session: 1/" + str(len(RETRAIN_ITER) + 1))
                else:
                    print("Training AE, this is training session: 1/" + str(len(RETRAIN_ITER) + 1))

        # Reset the optimizer
        vae.reset_optimizer_op
        
        # Get training and validation datasets
        ref_dataset = None
        if is_pretrained == False:
            ref_dataset = split_dataset(len(population))
        else:
            ref_dataset = dummy_split(len(population))

        print("Beginning Training of VAE")
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        print("Current Time =", current_time)            
        
        check_state = 50
        total_epochs = 0

        condition = True
        epoch = 0
        last_val_loss = 999999999999

        num_epoch = NUM_EPOCH

        for training_data, validation_data in ref_dataset:
            if total_epochs <= num_epoch * 2:
                condition = True
                epoch = 0
                last_val_loss = 999999999999

            # This condition controls the training session
            while (condition == True):
                
                #??Reset epoch losses
                t_loss = 0.0
                v_loss = 0.0

                if (epoch % 5 == 0):
                    print("At training epoch " + str(epoch) + ", we're " + str(int(epoch/num_epoch * 100)) + "% of the way there!")
                
                # Actual training
                for t in training_data:
                    member = population[t]
                    image = member.get_scaled_image(_max, _min)
                    _, _, loss, _, _ = session.run((vae.z, vae.decoded, vae.loss, vae.learning_rate, vae.train_step), \
                        feed_dict={vae.x : image, vae.keep_prob : 0, vae.global_step : epoch})
                    t_loss += np.mean(loss)

                t_loss_record.append(t_loss)


                # Calculate epoch validation loss
                if is_pretrained == False:
                    for v in validation_data:
                        member = population[v]
                        image = member.get_scaled_image(_max, _min)
                        loss = session.run((vae.loss), feed_dict={vae.x : image, vae.keep_prob : 0, vae.global_step : num_epoch})
                        v_loss += np.mean(loss)

                    v_loss_record.append(v_loss)

                    if len(v_loss_record) >= check_state:
                        # Get the last 500 values of validation loss
                        calc_avg_loss = v_loss_record[-check_state:]
                        # Calculate the average
                        calc_avg_loss = np.mean(calc_avg_loss)

                        # If validation loss has increased OR if max epoch count has been reached, stop the training session
                        if (calc_avg_loss > last_val_loss):
                            condition = False
                        
                        else:
                            # Record new value to use as previous validation loss
                            last_val_loss = calc_avg_loss

                if (epoch == num_epoch):
                        condition = False
                # Increase epoch counter
                else:
                    epoch += 1
                    total_epochs += 1

        # Save the current VAE
        model_name = prefix + "/MY_MODEL"
        vae.saver.save(session, model_name)

    print("Training Complete")
    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    print("Current Time =", current_time)

    plt.clf()
    plt.plot(t_loss_record, label="Training Loss")
    plt.plot(v_loss_record, label="Validation Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Reconstruction Loss")
    plt.legend()
    title = None
    if when_trained == 0:
        if is_vae:
            title = "Loss when VAE Initially Trained"
        else:
            title = "Loss when AE Initially Trained"
    else:
        if is_vae:
            title = "Loss when VAE Retrained at Generation/Batch " + str(when_trained)
        else:
            title = "Loss when AE Retrained at Generation/Batch " + str(when_trained)
    plt.title(title)
    if is_vae:
        save_name = prefix + "/myplots/Loss_VAE_Trained_"+str(when_trained)
    else:
        save_name = prefix + "/myplots/Loss_AE_Trained_"+str(when_trained)
    plt.savefig(save_name)
    return vae, t_loss_record, v_loss_record

# Returns current Kullback-Leibler Coverage
def KLC(population, true_gt):
    nb_bins = 30

    # Get the "ground truth", aka the manually defined behavioural descriptor, and the current encoder latent space
    my_gt_0 = []
    my_gt_1 = []
    true_gt_0 = true_gt[0]
    true_gt_1 = true_gt[1]
    for member in population:
        gt = member.get_gt()
        my_gt_0.append(gt[0])
        my_gt_1.append(gt[1])

    # Get normalized histograms of the data
    l_norm_0, _, _ = plt.hist(my_gt_0, bins=nb_bins, range = [-1.0, 1.0])
    l_norm_1, _, _ = plt.hist(my_gt_1, bins=nb_bins, range = [-1.0, 1.0])

    g_norm_0, _, _ = plt.hist(true_gt_0, bins=nb_bins, range = [-1.0, 1.0])
    g_norm_1, _, _ = plt.hist(true_gt_1, bins=nb_bins, range = [-1.0, 1.0])


    g_norm_0 /= sum(g_norm_0)
    g_norm_1 /= sum(g_norm_1)
    l_norm_0 /= sum(l_norm_0)
    l_norm_1 /= sum(l_norm_1)

    for i in range(nb_bins):
        # Case controlis necessary as these histograms exist to act as pseudo probability distributions
        # In histograms, a bin may have 0 values
        # In a probability distribution, there is always a minor chance something can happend
        # So if any values are explicit 0s, we set them to a very small number to avoid log(0)

        if g_norm_0[i] == 0.0:
            g_norm_0[i] = 0.00000001

        if l_norm_0[i] == 0.0:
            l_norm_0[i] = 0.00000001
        
        if g_norm_1[i] == 0.0:
            g_norm_1[i]= 0.00000001

        if l_norm_1[i] == 0.0:
            l_norm_1[i] = 0.00000001

    D_KL_0 = 0.0
    D_KL_1 = 0.0

    for i in range(nb_bins):
        D_KL_0 += g_norm_0[i] * math.log(g_norm_0[i]/l_norm_0[i])
        D_KL_1 += g_norm_1[i] * math.log(g_norm_1[i]/l_norm_1[i])

    return D_KL_0, D_KL_1

# Returns new novelty threshold
def calculate_novelty_threshold(latent_space):

    rows = len(latent_space)
    cols = len(latent_space[0][0])
    X = np.zeros((rows, cols))
    for i in range(rows):
        for j in range(cols):
            X[i][j] = latent_space[i][0][j]

    XX = np.zeros((rows, 1))

    for i in range(rows):
        sigma = 0
        for j in range(cols):
            sigma += X[i][j]**2
        XX[i][0] = sigma

    XY = (2*X) @ X.T

    dist = XX @ np.ones((1, rows))
    dist += np.ones((rows, 1)) @ XX.T
    dist -= XY

    maxdist = np.sqrt(np.max(dist))

    # Arbitrary value to have a specific "resolution"
    # Increase to decrease novelty threshold and make it easier to add individuals
    # Decrease to increase novelty threshold and make it harder to add indiivduals
    K = 60000
    
    new_novelty = maxdist/np.sqrt(K)
    return new_novelty

# Returns parameters needed to calculate novelty
def make_novelty_params(population):

    rows = len(population)
    cols = 2
    X = np.zeros((rows, cols))
    for i in range(rows):
        this_bd = population[i].get_bd()[0]
        X[i][0] = this_bd[0]
        X[i][1] = this_bd[1]

    x_squared = np.zeros((rows, 1))
    two_x = np.zeros((rows, 1))
    y_squared = np.zeros((rows, 1))
    two_y = np.zeros((rows, 1))

    for i in range(rows):
        x_squared[i] = X[i][0]**2
        two_x[i] = 2 * X[i][0]
        y_squared[i] = X[i][1]**2
        two_y[i] = 2 * X[i][1]

    return x_squared, two_x, y_squared, two_y

# Returns mutated individual (10% chance)
def mut_eval(indiv_params):
    # Implements polynomial mutation
    new_indiv = individual.indiv()
    new_params = indiv_params.copy()
    for p in range(len(indiv_params)):
        mutate = random.uniform(0, 1)
        if mutate < MUTATION_RATE:
            u = random.uniform(0, 1)
            if u <= 0.5:
                # Calculate delta_L
                delta_L = (2 * u)**(1 / (1 + ETA)) - 1
                new_params[p] = indiv_params[p] + delta_L * (indiv_params[p] - FIT_MIN)
            else:
                # Calculate delta_R
                delta_R = 1 - (2 * ( (1-u))**(1/ (1 + ETA) ) )
                new_params[p] = indiv_params[p] + delta_R * (FIT_MAX - indiv_params[p])

    new_indiv.eval(new_params)
    return new_indiv

# Returns True if new_guy is both different from old_guy and if new_guy is within legal bounds
def is_indiv_legal(new_guy, old_guy):
    get_key = new_guy.get_key()
    get_parent_key = old_guy.get_key()
    ret_type = False
    if FIT_MIN <= get_key[0] <= FIT_MAX and FIT_MIN <= get_key[1] <= FIT_MAX:
        if get_key[0] != get_parent_key[0] or get_key[1] != get_parent_key[1]:
            ret_type = True
    return ret_type

# Check domination when re-adding to populaiton
def grow_pop_does_dominate(curr_threshold, k_n_n, dist_from_k_n_n, population, init_novelty):
    dominated_indiv = -1
    x_1_novelty = init_novelty
    # If novelty threshold is greater than the nearest neighbour but less than the second nearest neighbour
    if (curr_threshold > dist_from_k_n_n[0]) and (curr_threshold < dist_from_k_n_n[1]):

        pop_without_x_2 = population.copy()
        del pop_without_x_2[k_n_n[0]]
        x_1_novelty = dist_from_k_n_n[1]
        x_2_novelty, _ = grow_pop_calculate_novelty(population[k_n_n[0]].get_bd(), pop_without_x_2, curr_threshold, False)

        # Find if exclusive epsilon dominance is met according to Cully QD Framework
        # First Condition
        if x_1_novelty >= (1 - EPSILON) * x_2_novelty:
            # The Second Condition measures Quality, i.e. a fitness function
            # In AURORA this does not exist as having such a defeats the purpose of autonomous discovery
            #??I have included because why the hell not
            # if Q(new_indiv) >= (1 - ETA) * Q(nearest_neighbour)

            # The Third Condition is another bound that measures the combination of Novelty and Quality
            #             Quality
            #               |      .
            #               |      .    Idea is that this area 
            #               |      .    dominates
            #               |      ........
            #               |
            #               |
            #                -------------- Novelty

            dominated_indiv = k_n_n[0]

    return dominated_indiv, x_1_novelty

#??Returns novelty of an individual when re-adding to population    
def grow_pop_calculate_novelty(this_bd, population, curr_threshold, check_dominate):
    # If the population is still too small
    if len(population) < K_NEAREST_NEIGHBOURS:
        novelty = 99999
        return novelty, -1
    else:
        k_n_n = []
        dist_from_k_n_n = []
        for member in range(len(population)):
            coord = population[member].get_bd()
            dist = np.linalg.norm(this_bd - coord)
            if len(dist_from_k_n_n) < K_NEAREST_NEIGHBOURS:
                dist_from_k_n_n.append(dist)
                k_n_n.append(member)
            else:
                # Sort lists so that minimum novelty is at the start
                k_n_n = [x for _,x in sorted(zip(dist_from_k_n_n, k_n_n))]
                dist_from_k_n_n.sort()
                #??Is new novelty larger?
                if dist < dist_from_k_n_n[-1]:
                    dist_from_k_n_n[-1] = dist
                    k_n_n[-1] = member

        # Sort lists so that minimum novelty is at the start
        k_n_n = [x for _,x in sorted(zip(dist_from_k_n_n, k_n_n))]
        dist_from_k_n_n.sort()
        novelty = dist_from_k_n_n[0]

        dominated_indiv = -1

        if check_dominate:
            dominated_indiv, novelty = grow_pop_does_dominate(curr_threshold, k_n_n, dist_from_k_n_n, population, novelty)

        return novelty, dominated_indiv

# Check domination, i.e. if domination conditions have been met
def does_dominate(curr_threshold, k_n_n, dist_from_k_n_n, x_squared, two_x, y_squared, two_y, population):
    dominated_indiv = -1
    x_1_novelty = dist_from_k_n_n[0]
    if (curr_threshold > dist_from_k_n_n[0]) and (curr_threshold < dist_from_k_n_n[1]):
        x_1_novelty = dist_from_k_n_n[1]
        x_2_novelty, _ = calculate_novelty(population[k_n_n[0]].get_bd(), curr_threshold, False, x_squared, two_x, y_squared, two_y, population)
        if x_1_novelty >= (1 - EPSILON) * x_2_novelty:
            dominated_indiv = k_n_n[0]

    return dominated_indiv, x_1_novelty

# Returns novelty of individual
def calculate_novelty(this_bd, curr_threshold, check_dominate, x_squared, two_x, y_squared, two_y, population):
    this_bd = this_bd[0]
    two_x_new_x = two_x * this_bd[0]
    two_y_new_y = two_y * this_bd[1]
    size = len(x_squared)
    new_x_squared = np.full((size, 1), this_bd[0]**2)
    new_y_squared = np.full((size, 1), this_bd[1]**2)

    sq_distances = x_squared - two_x_new_x + new_x_squared + y_squared - two_y_new_y + new_y_squared
    if np.min(sq_distances) < 0:
        index = np.argmin(sq_distances)
        sq_distances[index] = 0

    min_dist = np.sqrt(np.min(sq_distances))
    nn = np.argmin(sq_distances)

    sq_distances[nn] = 99999999

    second_min_dist = np.sqrt(np.min(sq_distances))
    second_nn = np.argmin(sq_distances)

    novelty = min_dist

    dominated_indiv = -1

    if check_dominate:
        dominated_indiv, novelty = does_dominate(curr_threshold, [nn, second_nn], [min_dist, second_min_dist], x_squared, two_x, y_squared, two_y, population)
    else:
        novelty = second_min_dist

    return novelty, dominated_indiv

# Plots the latent space and the ground truth
def plot_latent_gt(population, when_trained, prefix):
    l_x = []
    l_y = []
    g_x = []
    g_y = []

    for member in population:
        this_x, this_y = member.get_bd()[0]
        l_x.append(this_x)
        l_y.append(this_y)
        this_x, this_y = member.get_gt()
        g_x.append(this_x)
        g_y.append(this_y)

    t = np.arange(len(population))

    euclidean_from_zero_gt = []
    for i in range(len(g_x)):
        distance = g_x[i]**2 + g_y[i]**2
        euclidean_from_zero_gt.append(distance)
    

    g_x = [x for _,x in sorted(zip(euclidean_from_zero_gt, g_x))]
    g_y = [y for _,y in sorted(zip(euclidean_from_zero_gt, g_y))]
    l_x = [x for _,x in sorted(zip(euclidean_from_zero_gt, l_x))]
    l_y = [y for _,y in sorted(zip(euclidean_from_zero_gt, l_y))]

    plt.clf()
    plt.scatter(l_x, l_y, c=t, cmap="rainbow", s=1)
    plt.xlabel("Encoded dimension 1")
    plt.ylabel("Encoded dimension 2")
    title = None
    if when_trained == 0:
        title = "Latent Space at Initialisation"
    elif when_trained == -1:
        title = "Latent Space at Final Generation"
    else:
        title = "Latent Space when at Generation/Batch " + str(when_trained)
    
    plt.title(title)
    save_name = prefix + "/myplots/Latent_Space_" + str(when_trained)
    plt.savefig(save_name)

    plt.clf()
    plt.scatter(g_x, g_y, c=t, cmap="rainbow", s=1)
    plt.xlabel("X position at Max Height")
    plt.ylabel("Max Height Achieved")
    plt.xlim(-1.25,1.15)
    plt.ylim(-1.15,1)
    title = None
    if when_trained == 0:
        title = "Ground Truth at nitialisation"
    elif when_trained == -1:
        title = "Ground Truth at Final Generation"
    else:
        title = "Ground Truth at Generation/Batch " + str(when_trained)
    plt.title(title)
    save_name = prefix + "/myplots/Ground_Truth_" + str(when_trained)
    plt.savefig(save_name)

# Plots the ground truth only
def plot_gt(population, when_trained, prefix):
    g_x = []
    g_y = []

    for member in population:
        this_x, this_y = member.get_gt()
        g_x.append(this_x)
        g_y.append(this_y)

    t = np.arange(len(population))

    euclidean_from_zero_gt = []
    for i in range(len(g_x)):
        distance = g_x[i]**2 + g_y[i]**2
        euclidean_from_zero_gt.append(distance)

    g_x = [x for _,x in sorted(zip(euclidean_from_zero_gt, g_x))]
    g_y = [y for _,y in sorted(zip(euclidean_from_zero_gt, g_y))]

    plt.clf()
    plt.scatter(g_x, g_y, c=t, cmap="rainbow", s=1)
    plt.xlabel("X position at Max Height")
    plt.ylabel("Max Height Achieved")
    plt.xlim(-1.25,1.15)
    plt.ylim(-1.15,1)
    title = None
    if when_trained == 0:
        title = "Ground Truth at Initialisation"
    elif when_trained == -1:
        title = "Ground Truth at Final Generation"
    else:
        title = "Ground Truth at Generation " + str(when_trained)
    plt.title(title)
    save_name = prefix + "/myplots/Ground_Truth_"+str(when_trained)
    plt.savefig(save_name)

# Function to make the curiosity proportionate roulette wheel
def make_wheel(population):
    literal_roulette_curiosities = []
    min_cur = 999999999.9
    for member in population:                  
        cur = member.get_curiosity()
        literal_roulette_curiosities.append(cur)
        if cur < min_cur:
            min_cur = cur
    if min_cur < 0:
        min_cur = -1 * min_cur

    # Shift all curiosity values by the minimum curiosity in the population
    # Curiosity offset is necessary otherwise at initialisation nothing will work AND no new member of the population will be selected
    offset_roulette_curiosities = [ cur + min_cur + CURIOSITY_OFFSET for cur in literal_roulette_curiosities ]

    # Calculate proportionate wheel by dividing wheel by sum
    roulette_sum = sum(offset_roulette_curiosities)
    roulette_wheel = [ cur / roulette_sum for cur in offset_roulette_curiosities]
    return roulette_wheel
    
# Runs AURORA PCA pretrained version, i.e. only runs PCA once and with more samples    
def AURORA_pretrained_PCA(prefix):
    comparison_gt = np.load("GROUND_TRUTH.npy")
    # Uniformly sample some controllers                           
    dim = 54
    init_size = dim * dim                           # Initial size of population
    print("Creating population container")
    training_pop = [individual.indiv() for b in range(init_size)] # Container for training population
    print("Complete")

    print("Evaluating population")
    step_size = (FIT_MAX - FIT_MIN)/dim
    genotype = [FIT_MIN, FIT_MIN]
    for member in training_pop:
        if genotype[1] > FIT_MAX:
            genotype[1] = FIT_MIN
            genotype[0] += step_size
        member.eval(genotype)
        genotype[1] += step_size
    print("Complete")

    # # Create the dimension reduction algorithm (the PCA)
    print("Creating and Training PCA")
    # Train the dimension reduction algorithm (the PCA) on the dataset 
    _max, _min = get_scaling_vars(training_pop)
    training_pop_data = np.squeeze(np.array([member.get_scaled_image(_max, _min) for member in training_pop]))
    my_pca = cuPCA(n_components=2,output_type='numpy').fit(training_pop_data)

    init_size = POPULATION_INITIAL_SIZE            # Initial size of population
    print("Creating population container")
    pop = [individual.indiv() for b in range(init_size)] # Container for population
    print("Complete")
    
    print("Evaluating current population")
    for member in pop:
        genotype = [random.uniform(FIT_MIN, FIT_MAX), random.uniform(FIT_MIN, FIT_MAX)]
        member.eval(genotype)
    print("Complete")

    _max, _min = get_scaling_vars(pop)

    # Create container for latent space representation
    latent_space = []
    
    # Set BDs and fill latent space
    images = np.squeeze(np.array([member.get_scaled_image(_max, _min) for member in pop]))
    member_bds = my_pca.transform(images)
    member_bds = np.expand_dims(member_bds,axis=1)
    for member, member_bd in zip(pop, member_bds):
        member.set_bd(member_bd.copy())
        latent_space.append(member_bd.copy())

    # Record current latent space
    plot_latent_gt(pop, 0, prefix)

    # Calculate starting novelty threshold
    threshold = calculate_novelty_threshold(latent_space)

    # These are needed for the main algorithm
    klc_log = [[], []]
    roulette_wheel = []
    repertoire_size = []
    big_error_log = [ [] for i in range(2) ]
    rmse_log = []

    print_index = 0
    
    print("Starting Main AURORA Algorithm")
    # Main AURORA algorithm, for 5000 generations, run 200 evaluations, and retrain the network at specific generations
    for generation in range(NB_QD_BATCHES):
        _max, _min = get_scaling_vars(pop)

        roulette_wheel = make_wheel(pop)
        x_squared, two_x, y_squared, two_y = make_novelty_params(pop)
        if print_index < len(PRINT_ITER):
            if generation == PRINT_ITER[print_index]:
                plot_latent_gt(pop, generation, prefix)
                print_index += 1
        
        if generation != 0 and generation % 100 == 0:
            print(klc_log[0][-1], klc_log[1][-1])
        if generation % 50 == 0:
            print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))
        print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))


        # Begin Quality Diversity iterations
        gen_rmse_log = []

        for j in range(NB_QD_ITERATIONS):

            # 1. Select controller from population using curiosity proportionate selection
            selector = random.uniform(0, 1)
            index = 0
            cumulative = roulette_wheel[index]
            while (selector >= cumulative ) and (index != len(roulette_wheel)-1):
                index += 1
                cumulative += roulette_wheel[index]
            this_indiv = pop[index]

            controller = this_indiv.get_key()

            # 2. Mutate and evaluate the chosen controller
            new_indiv = mut_eval(controller)

            if is_indiv_legal(new_indiv, this_indiv) == True:
                new_bd = None
                out = None
                image = None

                # 3. Get the Behavioural Descriptor for the new individual
                image = new_indiv.get_scaled_image(_max, _min)
                new_bd = my_pca.transform(image) 

                out = my_pca.inverse_transform(new_bd)    
                gen_rmse_log.append(np.sqrt(np.mean((image - out)**2)))

                # 4. See if the new Behavioural Descriptor is novel enough
                novelty, dominated = calculate_novelty(new_bd, threshold, True, x_squared, two_x, y_squared, two_y, pop)
                # 5. If the new individual has novel behaviour, add it to the population and the BD to the latent space
                if dominated == -1:                           #    If the individual did not dominate another individual
                    if novelty >= threshold:                  #    If the individual is novel
                        new_indiv.set_bd(new_bd.copy())
                        pop.append(new_indiv)

                        # Increase curiosity score of individual
                        pop[index].increase_curiosity()

                    else:                                    #    If the individual is NOT novel
                        # Decrease curiosity score of individual
                        pop[index].decrease_curiosity()
                else:                                         #    If the individual dominated another individual
                    new_indiv.set_bd(new_bd.copy())
                    pop[dominated] = new_indiv

                    # Increase curiosity score of individual
                    pop[index].increase_curiosity()

        # 6. For each batch/generation, record various metrics
        current_klc_0, current_klc_1 = KLC(pop, comparison_gt)
        klc_log[0].append(current_klc_0)
        klc_log[1].append(current_klc_1)
        repertoire_size.append(len(pop))
        rmse_log.append(np.mean(gen_rmse_log))


    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    print("Current Time =", current_time)

    plt.clf()
    plt.plot(klc_log[0], label="x")
    plt.plot(klc_log[1], label="y")
    plt.legend()
    plt.xlabel("Generation")
    plt.ylabel("KLC Score")
    title = "Kullback-Leibler Coverage, KL Divergence (Ground Truth || Generated BD)"
    plt.title(title)
    save_name = prefix + "/myplots/KLC"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_KLC.npy"
    np.save(np_name, klc_log)

    plt.clf()
    plt.plot(repertoire_size, label="Repertoire Size")
    plt.xlabel("Generation")
    plt.ylabel("Number of controllers")
    title = "Repertoire Size"
    plt.title(title)
    save_name = prefix + "/myplots/RepSize"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_repSize.npy"
    np.save(np_name, repertoire_size)
    
    plot_latent_gt(pop, -1, prefix)

    plt.clf()
    plt.plot(big_error_log[0], label="Training Loss")
    plt.plot(big_error_log[1], label="Validation Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Reconstruction Loss")
    plt.legend()
    title = "Reconstruction Loss"
    plt.title(title)
    save_name = prefix + "/myplots/Full_loss_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_error_log.npy"
    np.save(np_name, big_error_log)

    plt.clf()
    plt.plot(rmse_log)
    plt.xlabel("Generation")
    plt.ylabel("RMSE Loss")
    title = "Average Root Mean Squared Error per Generation"
    plt.title(title)
    save_name = prefix + "/myplots/pre_rmse_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_rmse.npy"
    np.save(np_name, rmse_log)



# Runs AURORA PCA incremental version (i.e. with retraining periods)
def AURORA_incremental_PCA(prefix):
    comparison_gt = np.load("GROUND_TRUTH.npy")
    # Randomly generate some controllers
    init_size = POPULATION_INITIAL_SIZE            # Initial size of population
    print("Creating population container")
    pop = [individual.indiv() for b in range(init_size)] # Container for training population
    print("Complete")

    # Collect sensory data of the generated controllers. In the case of the ballistic task this is the trajectories but any sensory data can be considered
    print("Evaluating current population")
    for member in pop:
        genotype = [random.uniform(FIT_MIN, FIT_MAX), random.uniform(FIT_MIN, FIT_MAX)]
        member.eval(genotype)
    print("Complete")

    # Create the dimension reduction algorithm (the PCA)
    print("Creating PCA")
    my_pca = cuPCA(n_components=2,output_type='numpy')

    # Create container for latent space representation
    latent_space = []

    _max, _min = get_scaling_vars(pop)
    # Train and use the PCA to get the behavioural descriptors
    images = np.squeeze(np.array([member.get_scaled_image(_max, _min) for member in pop]))
    member_bds = my_pca.fit_transform(images)
    member_bds = np.expand_dims(member_bds,axis=1)
    # Set BDs and fill latent space
    for member, member_bd in zip(pop, member_bds):
        member.set_bd(member_bd.copy())
        latent_space.append(member_bd.copy())
    
    # Record current latent space
    plot_latent_gt(pop, 0, prefix)

    # Calculate starting novelty threshold
    threshold = INITIAL_NOVELTY

    # These are needed for the main algorithm
    network_activation = 0
    klc_log = [[], []]
    just_finished_training = True
    roulette_wheel = []
    repertoire_size = []
    big_error_log = [ [] for i in range(2) ]
    # big_error_log[0] = t_error
    # big_error_log[1] = v_error

    rmse_log = []

    last_run = False
    
    print("Starting Main AURORA Algorithm")
    # Main AURORA algorithm, for 5000 generations, run 200 evaluations, and retrain the network at specific generations
    for generation in range(NB_QD_BATCHES):
        print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))
        _max, _min = get_scaling_vars(pop)        
        if generation != 0 and generation % 100 == 0:
            print(klc_log[0][-1], klc_log[1][-1])
        if just_finished_training:
            print("Beginning QD iterations, next UMAP retraining at generation " + str(RETRAIN_ITER[network_activation]))
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print("Current Time =", current_time)
            print("Reinitialising curiosity proportionate roulette wheel")
        if last_run:
            print("Beginning QD iterations, no more UMAP training")
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print("Current Time =", current_time)
            print("Reinitialising curiosity proportionate roulette wheel")
            last_run = False


        roulette_wheel = make_wheel(pop)
        x_squared, two_x, y_squared, two_y = make_novelty_params(pop)

        if generation % 50 == 0:
            print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))

        # Begin Quality Diversity iterations
        gen_rmse_log = []
        for j in range(NB_QD_ITERATIONS):

            # 1. Select controller from population using curiosity proportionate selection ( AKA Spin wheel! )
            selector = random.uniform(0, 1)
            index = 0
            cumulative = roulette_wheel[index]
            while (selector >= cumulative ) and (index != len(roulette_wheel)-1):
                index += 1
                cumulative += roulette_wheel[index]
            this_indiv = pop[index]
            controller = this_indiv.get_key()

            # 2. Mutate and evaluate the chosen controller
            new_indiv = mut_eval(controller)
            if is_indiv_legal(new_indiv, this_indiv) == True:
                new_bd = None
                out = None
                image = None

                # 3. Get the Behavioural Descriptor for the new individual
                image = new_indiv.get_scaled_image(_max, _min)
                new_bd = my_pca.transform(image) 

                out = my_pca.inverse_transform(new_bd)     
                gen_rmse_log.append(np.sqrt(np.mean((image - out)**2)))

                # 4. See if the new Behavioural Descriptor is novel enough

                novelty, dominated = calculate_novelty(new_bd, threshold, True, x_squared, two_x, y_squared, two_y, pop)
                # 5. If the new individual has novel behaviour, add it to the population and the BD to the latent space
                if dominated == -1:                           #    If the individual did not dominate another individual
                    if novelty >= threshold:                  #    If the individual is novel
                        new_indiv.set_bd(new_bd.copy())
                        pop.append(new_indiv)

                        # Increase curiosity score of individual
                        pop[index].increase_curiosity()

                    else:                                    #    If the individual is NOT novel
                        # Decrease curiosity score of individual
                        pop[index].decrease_curiosity()
                else:                                         #    If the individual dominated another individual
                    new_indiv.set_bd(new_bd.copy())
                    pop[dominated] = new_indiv

                    # Increase curiosity score of individual
                    pop[index].increase_curiosity()


        just_finished_training = False

        # Check if this generation is before the last retraining session
        if network_activation < len(RETRAIN_ITER):
            if generation == RETRAIN_ITER[network_activation]:
                print("Finished QD iterations")
                now = datetime.now()
                current_time = now.strftime("%H:%M:%S")
                print("Current Time =", current_time)
                print("Current size of population is " + str(len(pop)))

                # 6. Retrain PCA after a number of QD iterations
                print("Training PCA, this is training session: " + str(network_activation + 2) + "/" + str(len(RETRAIN_ITER) + 1))
                _max, _min = get_scaling_vars(pop)
                images = np.squeeze(np.array([member.get_scaled_image(_max, _min) for member in pop]))
                member_bds = my_pca.fit_transform(images)
                member_bds = np.expand_dims(member_bds,1)
                print("Completed retraining")


                # 7. Clear latent space
                latent_space = []

                # 8. Assign the members of the population the new Behavioural Descriptors and refill the latent space
                _max, _min = get_scaling_vars(pop)
                for member, member_bd in zip(pop, member_bds):
                    member.set_bd(member_bd.copy())
                    latent_space.append(member_bd.copy())
                
                # 9. Calculate new novelty threshold to ensure population size less than 10000
                threshold = calculate_novelty_threshold(latent_space)
                print("New novelty threshold is " + str(threshold))

                # 10. Update population so that only members with novel bds are allowed
                print("Add viable members back to population")
                new_pop = []
                for member in pop:
                    this_bd = member.get_bd().copy()
                    novelty, dominated = grow_pop_calculate_novelty(this_bd, new_pop, threshold, True)
                    if dominated == -1:                           #    If the individual did not dominate another individual
                        if novelty >= threshold:                  #    If the individual is novel
                            new_pop.append(member)
                    else:                                         #    If the individual dominated another individual
                        new_pop[dominated] = member

                pop = new_pop
                print("After re-training, size of population is " + str(len(pop)))

                # 11. Get current Latent Space and Ground Truth plots
                plot_latent_gt(pop, generation, prefix)

                # 12. Prepare to check next retrain period
                network_activation += 1
                if network_activation == len(RETRAIN_ITER):
                    last_run = True
                else:
                    just_finished_training = True
            
        # 13. For each batch/generation, record various metrics
        current_klc_0, current_klc_1 = KLC(pop, comparison_gt)
        klc_log[0].append(current_klc_0)
        klc_log[1].append(current_klc_1)
        repertoire_size.append(len(pop))
        rmse_log.append(np.mean(gen_rmse_log))

    plt.clf()
    plt.plot(klc_log[0], label="x")
    plt.plot(klc_log[1], label="y")
    plt.legend()
    plt.xlabel("Generation")
    plt.ylabel("KLC Score")
    title = "Kullback-Leibler Coverage, KL Divergence (Ground Truth || Generated BD)"
    plt.title(title)
    save_name = prefix + "/myplots/KLC"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_KLC.npy"
    np.save(np_name, klc_log)

    plt.clf()
    plt.plot(repertoire_size, label="Repertoire Size")
    plt.xlabel("Generation")
    plt.ylabel("Number of controllers")
    title = "Repertoire Size"
    plt.title(title)
    save_name = prefix + "/myplots/RepSize"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_repSize.npy"
    np.save(np_name, repertoire_size)
    
    plot_latent_gt(pop, -1, prefix)

    plt.clf()
    plt.plot(big_error_log[0], label="Training Loss")
    plt.plot(big_error_log[1], label="Validation Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Reconstruction Loss")
    plt.legend()
    title = "Reconstruction Loss"
    plt.title(title)
    save_name = prefix + "/myplots/Full_loss_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_error_log.npy"
    np.save(np_name, big_error_log)

    plt.clf()
    plt.plot(rmse_log)
    plt.xlabel("Generation")
    plt.ylabel("RMSE Loss")
    title = "Average Root Mean Squared Error per Generation"
    plt.title(title)
    save_name = prefix + "/myplots/inc_rmse_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_rmse.npy"
    np.save(np_name, rmse_log)
    

# Runs AURORA pretrained version, i.e. only trains variational autoencoder once and with more samples    
def AURORA_pretrained_VAE(prefix,is_vae):
    comparison_gt = np.load("GROUND_TRUTH.npy")
    # Uniformly sample some controllers
    dim = 100
    init_size = dim * dim                           # Initial size of population
    print("Creating population container")
    training_pop = [individual.indiv() for b in range(init_size)] # Container for training population
    print("Complete")

    print("Evaluating population")
    step_size = (FIT_MAX - FIT_MIN)/dim
    genotype = [FIT_MIN, FIT_MIN]
    for member in training_pop:
        if genotype[1] > FIT_MAX:
            genotype[1] = FIT_MIN
            genotype[0] += step_size
        member.eval(genotype)
        genotype[1] += step_size
    print("Complete")

    # Create the dimension reduction algorithm (the variational autoencoder)
    print("Creating network, printing variational autoencoder (VAE) layers")
    if is_vae:
        my_vae = VAE(NUM_EPOCH)
    else:
        my_vae = AE(NUM_EPOCH)

    # Train the dimension reduction algorithm (the VAE) on the dataset
    my_vae, t_error, v_error = train_vae(prefix, my_vae, training_pop, 0, True, is_vae)

    init_size = POPULATION_INITIAL_SIZE            # Initial size of population
    print("Creating population container")
    pop = [individual.indiv() for b in range(init_size)] # Container for population
    print("Complete")
    print("Evaluating current population")
    for member in pop:
        genotype = [random.uniform(FIT_MIN, FIT_MAX), random.uniform(FIT_MIN, FIT_MAX)]
        member.eval(genotype)
    print("Complete")

    _max, _min = get_scaling_vars(pop)

    # Create container for latent space representation
    latent_space = []

    # Set BDs and fill latent space
    with tf.Session() as sess:
        model_name = prefix + "/MY_MODEL"
        my_vae.saver.restore(sess, model_name)
        for member in pop:
            image = member.get_scaled_image(_max, _min)
            member_bd = sess.run(my_vae.mu, feed_dict={my_vae.x : image, my_vae.keep_prob : 0, my_vae.global_step : NUM_EPOCH})
            member.set_bd(member_bd.copy())
            latent_space.append(member_bd.copy())
            
    # Record current latent space
    plot_latent_gt(pop, 0, prefix)

    # Calculate starting novelty threshold
    threshold = calculate_novelty_threshold(latent_space)

    # These are needed for the main algorithm
    klc_log = [[], []]
    roulette_wheel = []
    repertoire_size = []
    big_error_log = [ [] for i in range(2) ]
    big_error_log[0] = t_error
    big_error_log[1] = v_error
    rmse_log = []

    print_index = 0
    
    
    print("Starting Main AURORA Algorithm")
    # Main AURORA algorithm, for 5000 generations, run 200 evaluations, and retrain the network at specific generations
    for generation in range(NB_QD_BATCHES):
        _max, _min = get_scaling_vars(pop)

        roulette_wheel = make_wheel(pop)
        x_squared, two_x, y_squared, two_y = make_novelty_params(pop)
        if print_index < len(PRINT_ITER):
            if generation == PRINT_ITER[print_index]:
                plot_latent_gt(pop, generation, prefix)
                print_index += 1
        
        if generation != 0 and generation % 100 == 0:
            print(klc_log[0][-1], klc_log[1][-1])
        if generation % 50 == 0:
            print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))
        

        # Begin Quality Diversity iterations
        with tf.Session() as sess:
            gen_rmse_log = []
            model_name = prefix + "/MY_MODEL"
            my_vae.saver.restore(sess, model_name)

            for j in range(NB_QD_ITERATIONS):

                # 1. Select controller from population using curiosity proportionate selection
                selector = random.uniform(0, 1)
                index = 0
                cumulative = roulette_wheel[index]
                while (selector >= cumulative ) and (index != len(roulette_wheel)-1):
                    index += 1
                    cumulative += roulette_wheel[index]
                this_indiv = pop[index]

                controller = this_indiv.get_key()

                # 2. Mutate and evaluate the chosen controller
                new_indiv = mut_eval(controller)

                if is_indiv_legal(new_indiv, this_indiv) == True:
                    new_bd = None
                    out = None
                    image = None

                    # 3. Get the Behavioural Descriptor for the new individual
                    image = new_indiv.get_scaled_image(_max, _min)
                    new_bd, out = sess.run((my_vae.mu, my_vae.decoded), feed_dict={my_vae.x : image, my_vae.keep_prob : 0, my_vae.global_step : NUM_EPOCH})

                    gen_rmse_log.append(np.sqrt(np.mean((image - out)**2)))

                    # 4. See if the new Behavioural Descriptor is novel enough

                    novelty, dominated = calculate_novelty(new_bd, threshold, True, x_squared, two_x, y_squared, two_y, pop)
                    # 5. If the new individual has novel behaviour, add it to the population and the BD to the latent space
                    if dominated == -1:                           #    If the individual did not dominate another individual
                        if novelty >= threshold:                  #    If the individual is novel
                            new_indiv.set_bd(new_bd.copy())
                            pop.append(new_indiv)

                            # Increase curiosity score of individual
                            pop[index].increase_curiosity()

                        else:                                    #    If the individual is NOT novel
                            # Decrease curiosity score of individual
                            pop[index].decrease_curiosity()
                    else:                                         #    If the individual dominated another individual
                        new_indiv.set_bd(new_bd.copy())
                        pop[dominated] = new_indiv

                        # Increase curiosity score of individual
                        pop[index].increase_curiosity()

        # 6. For each batch/generation, record various metrics
        current_klc_0, current_klc_1 = KLC(pop, comparison_gt)
        klc_log[0].append(current_klc_0)
        klc_log[1].append(current_klc_1)
        repertoire_size.append(len(pop))
        rmse_log.append(np.mean(gen_rmse_log))


    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    print("Current Time =", current_time)

    plt.clf()
    plt.plot(klc_log[0], label="x")
    plt.plot(klc_log[1], label="y")
    plt.legend()
    plt.xlabel("Generation")
    plt.ylabel("KLC Score")
    title = "Kullback-Leibler Coverage, KL Divergence (Ground Truth || Generated BD)"
    plt.title(title)
    save_name = prefix + "/myplots/KLC"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_KLC.npy"
    np.save(np_name, klc_log)

    plt.clf()
    plt.plot(repertoire_size, label="Repertoire Size")
    plt.xlabel("Generation")
    plt.ylabel("Number of controllers")
    title = "Repertoire Size"
    plt.title(title)
    save_name = prefix + "/myplots/RepSize"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_repSize.npy"
    np.save(np_name, repertoire_size)
    
    plot_latent_gt(pop, -1, prefix)

    plt.clf()
    plt.plot(big_error_log[0], label="Training Loss")
    plt.plot(big_error_log[1], label="Validation Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Reconstruction Loss")
    plt.legend()
    title = "Reconstruction Loss"
    plt.title(title)
    save_name = prefix + "/myplots/Full_loss_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_error_log.npy"
    np.save(np_name, big_error_log)

    plt.clf()
    plt.plot(rmse_log)
    plt.xlabel("Generation")
    plt.ylabel("RMSE Loss")
    title = "Average Root Mean Squared Error per Generation"
    plt.title(title)
    save_name = prefix + "/myplots/pre_rmse_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_rmse.npy"
    np.save(np_name, rmse_log)

# Runs AURORA incremental version (i.e. with retraining periods)
def AURORA_incremental_VAE(prefix, is_vae):
    comparison_gt = np.load("GROUND_TRUTH.npy")
    # Randomly generate some controllers
    init_size = POPULATION_INITIAL_SIZE            # Initial size of population
    print("Creating population container")
    pop = [individual.indiv() for b in range(init_size)] # Container for population
    print("Complete")

    # Collect sensory data of the generated controllers. In the case of the ballistic task this is the trajectories but any sensory data can be considered
    print("Evaluating current population")
    for member in pop:
        genotype = [random.uniform(FIT_MIN, FIT_MAX), random.uniform(FIT_MIN, FIT_MAX)]
        member.eval(genotype)
    print("Complete")

    # Create the dimension reduction algorithm (the Variational Autoencoder)
    print("Creating network, printing variational autoencoder layers")
    if is_vae:
        my_vae = VAE(NUM_EPOCH)
    else:
        my_vae = AE(NUM_EPOCH)

    # Train the dimension reduction algorithm (the VAE) on the dataset
    my_vae, t_error, v_error = train_vae(prefix, my_vae, pop, 0, False)

    # Create container for laten space representation
    latent_space = []

    _max, _min = get_scaling_vars(pop)

    # Use the now trained VAE to get the behavioural descriptors
    with tf.Session() as sess:
        model_name = prefix + "/MY_MODEL"
        my_vae.saver.restore(sess, model_name)
        for member in pop:
            image = member.get_scaled_image(_max, _min)
            # Sensory data is then projected into the latent space, this is used as the behavioural descriptor
            member_bd = sess.run(my_vae.mu, feed_dict={my_vae.x : image, my_vae.keep_prob : 0, my_vae.global_step : NUM_EPOCH})
            member.set_bd(member_bd.copy())
            latent_space.append(member_bd.copy())
    
    # Record current latent space
    plot_latent_gt(pop, 0, prefix)

    # Calculate starting novelty threshold
    threshold = INITIAL_NOVELTY

    # These are needed for the main algorithm
    network_activation = 0
    klc_log = [[], []]
    just_finished_training = True
    roulette_wheel = []
    repertoire_size = []
    big_error_log = [ [] for i in range(2) ]
    big_error_log[0] = t_error
    big_error_log[1] = v_error

    rmse_log = []

    last_run = False
    
    print("Starting Main AURORA Algorithm")
    # Main AURORA algorithm, for 5000 generations, run 200 evaluations, and retrain the network at specific generations
    for generation in range(NB_QD_BATCHES):
        _max, _min = get_scaling_vars(pop)        
        if generation != 0 and generation % 100 == 0:
            print(klc_log[0][-1], klc_log[1][-1])
        if just_finished_training:
            print("Beginning QD iterations, next Variational Autoencoder retraining at generation " + str(RETRAIN_ITER[network_activation]))
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print("Current Time =", current_time)
            print("Reinitialising curiosity proportionate roulette wheel")
        if last_run:
            if is_vae:
                print("Beginning QD iterations, no more VAE training")
            else:
                print("Beginning QD iterations, no more AE training")
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print("Current Time =", current_time)
            print("Reinitialising curiosity proportionate roulette wheel")
            last_run = False


        roulette_wheel = make_wheel(pop)
        x_squared, two_x, y_squared, two_y = make_novelty_params(pop)

        if generation % 50 == 0:
            print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))

        # Begin Quality Diversity iterations
        with tf.Session() as sess:
            model_name = prefix + "/MY_MODEL"
            my_vae.saver.restore(sess, model_name)
            # print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))
            gen_rmse_log = []
            for j in range(NB_QD_ITERATIONS):

                # 1. Select controller from population using curiosity proportionate selection ( AKA Spin wheel! )
                selector = random.uniform(0, 1)
                index = 0
                cumulative = roulette_wheel[index]
                while (selector >= cumulative ) and (index != len(roulette_wheel)-1):
                    index += 1
                    cumulative += roulette_wheel[index]
                this_indiv = pop[index]
                controller = this_indiv.get_key()

                # 2. Mutate and evaluate the chosen controller
                new_indiv = mut_eval(controller)
                if is_indiv_legal(new_indiv, this_indiv) == True:
                    new_bd = None
                    out = None
                    image = None

                    # 3. Get the Behavioural Descriptor for the new individual
                    image = new_indiv.get_scaled_image(_max, _min)
                    new_bd, out = sess.run((my_vae.mu, my_vae.decoded), feed_dict={my_vae.x : image, my_vae.keep_prob : 0, my_vae.global_step : NUM_EPOCH})

                    gen_rmse_log.append(np.sqrt(np.mean((image - out)**2)))

                    # 4. See if the new Behavioural Descriptor is novel enough

                    novelty, dominated = calculate_novelty(new_bd, threshold, True, x_squared, two_x, y_squared, two_y, pop)
                    # 5. If the new individual has novel behaviour, add it to the population and the BD to the latent space
                    if dominated == -1:                           #    If the individual did not dominate another individual
                        if novelty >= threshold:                  #    If the individual is novel
                            new_indiv.set_bd(new_bd.copy())
                            pop.append(new_indiv)

                            # Increase curiosity score of individual
                            pop[index].increase_curiosity()

                        else:                                    #    If the individual is NOT novel
                            # Decrease curiosity score of individual
                            pop[index].decrease_curiosity()
                    else:                                         #    If the individual dominated another individual
                        new_indiv.set_bd(new_bd.copy())
                        pop[dominated] = new_indiv

                        # Increase curiosity score of individual
                        pop[index].increase_curiosity()


        just_finished_training = False

        # Check if this generation is before the last retraining session
        if network_activation < len(RETRAIN_ITER):
            if generation == RETRAIN_ITER[network_activation]:
                print("Finished QD iterations")
                now = datetime.now()
                current_time = now.strftime("%H:%M:%S")
                print("Current Time =", current_time)
                print("Current size of population is " + str(len(pop)))

                # 6. Retrain VAE after a number of QD iterations
                if is_vae:
                    print("Training Variational Autoencoder (VAE), this is training session: " + str(network_activation + 2) + "/" + str(len(RETRAIN_ITER) + 1))
                else:
                    print("Training Autoencoder (AE), this is training session: " + str(network_activation + 2) + "/" + str(len(RETRAIN_ITER) + 1))
                my_vae, t_error, v_error = train_vae(prefix, my_vae, pop, generation, False)
                print("Completed retraining")

                tmp = t_error.copy()
                big_error_log[0] = big_error_log[0] + tmp
                tmp = v_error.copy()
                big_error_log[1] = big_error_log[1] + tmp

                # 7. Clear latent space
                latent_space = []

                # 8. Assign the members of the population the new Behavioural Descriptors and refill the latent space
                _max, _min = get_scaling_vars(pop)
                with tf.Session() as sess:
                    model_name = prefix + "/MY_MODEL"
                    my_vae.saver.restore(sess, model_name)
                    for member in pop:
                        this_bd = None
                        image = member.get_scaled_image(_max, _min)
                        member_bd = sess.run(my_vae.mu, feed_dict={my_vae.x : image, my_vae.keep_prob : 0, my_vae.global_step : NUM_EPOCH})
                        this_bd = member_bd.copy()

                        member.set_bd(this_bd.copy())
                        latent_space.append(this_bd.copy())

                # 9. Calculate new novelty threshold to ensure population size less than 10000
                threshold = calculate_novelty_threshold(latent_space)
                print("New novelty threshold is " + str(threshold))

                # 10. Update population so that only members with novel bds are allowed
                print("Add viable members back to population")
                new_pop = []
                for member in pop:
                    this_bd = member.get_bd().copy()
                    novelty, dominated = grow_pop_calculate_novelty(this_bd, new_pop, threshold, True)
                    if dominated == -1:                           #    If the individual did not dominate another individual
                        if novelty >= threshold:                  #    If the individual is novel
                            new_pop.append(member)
                    else:                                         #    If the individual dominated another individual
                        new_pop[dominated] = member

                pop = new_pop
                print("After re-training, size of population is " + str(len(pop)))

                # 11. Get current Latent Space and Ground Truth plots
                plot_latent_gt(pop, generation, prefix)

                # 12. Prepare to check next retrain period
                network_activation += 1
                if network_activation == len(RETRAIN_ITER):
                    last_run = True
                else:
                    just_finished_training = True
            
        # 13. For each batch/generation, record various metrics
        current_klc_0, current_klc_1 = KLC(pop, comparison_gt)
        klc_log[0].append(current_klc_0)
        klc_log[1].append(current_klc_1)
        repertoire_size.append(len(pop))
        rmse_log.append(np.mean(gen_rmse_log))

    plt.clf()
    plt.plot(klc_log[0], label="x")
    plt.plot(klc_log[1], label="y")
    plt.legend()
    plt.xlabel("Generation")
    plt.ylabel("KLC Score")
    title = "Kullback-Leibler Coverage, KL Divergence (Ground Truth || Generated BD)"
    plt.title(title)
    save_name = prefix + "/myplots/KLC"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_KLC.npy"
    np.save(np_name, klc_log)

    plt.clf()
    plt.plot(repertoire_size, label="Repertoire Size")
    plt.xlabel("Generation")
    plt.ylabel("Number of controllers")
    title = "Repertoire Size"
    plt.title(title)
    save_name = prefix + "/myplots/RepSize"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_repSize.npy"
    np.save(np_name, repertoire_size)
    
    plot_latent_gt(pop, -1, prefix)

    plt.clf()
    plt.plot(big_error_log[0], label="Training Loss")
    plt.plot(big_error_log[1], label="Validation Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Reconstruction Loss")
    plt.legend()
    title = "Reconstruction Loss"
    plt.title(title)
    save_name = prefix + "/myplots/Full_loss_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_error_log.npy"
    np.save(np_name, big_error_log)

    plt.clf()
    plt.plot(rmse_log)
    plt.xlabel("Generation")
    plt.ylabel("RMSE Loss")
    title = "Average Root Mean Squared Error per Generation"
    plt.title(title)
    save_name = prefix + "/myplots/inc_rmse_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_rmse.npy"
    np.save(np_name, rmse_log)


# Runs AURORA UMAP pretrained version, i.e. only runs UMAP once and with more samples    
def AURORA_pretrained_UMAP(prefix):
    comparison_gt = np.load("GROUND_TRUTH.npy")
    # Uniformly sample some controllers                           
    dim = 54
    init_size = dim * dim                           # Initial size of population
    print("Creating population container")
    training_pop = [individual.indiv() for b in range(init_size)] # Container for training population
    print("Complete")

    print("Evaluating population")
    step_size = (FIT_MAX - FIT_MIN)/dim
    genotype = [FIT_MIN, FIT_MIN]
    for member in training_pop:
        if genotype[1] > FIT_MAX:
            genotype[1] = FIT_MIN
            genotype[0] += step_size
        member.eval(genotype)
        genotype[1] += step_size
    print("Complete")

    # # Create the dimension reduction algorithm (the UMAP)
    print("Creating UMAP")
    # Train the dimension reduction algorithm (the UMAP) on the dataset 
    _max, _min = get_scaling_vars(training_pop)
    training_pop_data = np.squeeze(np.array([member.get_scaled_image(_max, _min) for member in training_pop]))
    my_umap = cuUMAP(n_neighbors=50, n_epochs=500, spread=1.5, min_dist=.2, hash_input=False).fit(training_pop_data)

    init_size = POPULATION_INITIAL_SIZE            # Initial size of population
    print("Creating population container")
    pop = [individual.indiv() for b in range(init_size)] # Container for population
    print("Complete")
    
    print("Evaluating current population")
    for member in pop:
        genotype = [random.uniform(FIT_MIN, FIT_MAX), random.uniform(FIT_MIN, FIT_MAX)]
        member.eval(genotype)
    print("Complete")

    _max, _min = get_scaling_vars(pop)

    # Create container for latent space representation
    latent_space = []
    
    # Set BDs and fill latent space
    images = np.squeeze(np.array([member.get_scaled_image(_max, _min) for member in pop]))
    member_bds = my_umap.transform(images)
    member_bds = np.expand_dims(member_bds,axis=1)
    for member, member_bd in zip(pop, member_bds):
        member.set_bd(member_bd.copy())
        latent_space.append(member_bd.copy())

    # Record current latent space
    plot_latent_gt(pop, 0, prefix)

    # Calculate starting novelty threshold
    threshold = calculate_novelty_threshold(latent_space)

    # These are needed for the main algorithm
    klc_log = [[], []]
    roulette_wheel = []
    repertoire_size = []
    big_error_log = [ [] for i in range(2) ]
    # rmse_log = []

    print_index = 0
    
    print("Starting Main AURORA Algorithm")
    # Main AURORA algorithm, for 5000 generations, run 200 evaluations, and retrain the network at specific generations
    for generation in range(NB_QD_BATCHES):
        _max, _min = get_scaling_vars(pop)

        roulette_wheel = make_wheel(pop)
        x_squared, two_x, y_squared, two_y = make_novelty_params(pop)
        if print_index < len(PRINT_ITER):
            if generation == PRINT_ITER[print_index]:
                plot_latent_gt(pop, generation, prefix)
                print_index += 1
        
        if generation != 0 and generation % 100 == 0:
            print(klc_log[0][-1], klc_log[1][-1])
        if generation % 50 == 0:
            print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))
        print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))


        # Begin Quality Diversity iterations
        # gen_rmse_log = []

        for j in range(NB_QD_ITERATIONS):

            # 1. Select controller from population using curiosity proportionate selection
            selector = random.uniform(0, 1)
            index = 0
            cumulative = roulette_wheel[index]
            while (selector >= cumulative ) and (index != len(roulette_wheel)-1):
                index += 1
                cumulative += roulette_wheel[index]
            this_indiv = pop[index]

            controller = this_indiv.get_key()

            # 2. Mutate and evaluate the chosen controller
            new_indiv = mut_eval(controller)

            if is_indiv_legal(new_indiv, this_indiv) == True:
                new_bd = None
                out = None
                image = None

                # 3. Get the Behavioural Descriptor for the new individual
                image = new_indiv.get_scaled_image(_max, _min)
                new_bd = np.expand_dims(my_umap.transform(np.append(images,image,0))[-1,:],0) # GPU method does not allow for single point transform (k-nn algorithm)
                # out = my_umap.inverse_transform(new_bd)     #    Not supported on GPU version of UMAP 
                # gen_rmse_log.append(np.sqrt(np.mean((image - out)**2)))

                # 4. See if the new Behavioural Descriptor is novel enough
                novelty, dominated = calculate_novelty(new_bd, threshold, True, x_squared, two_x, y_squared, two_y, pop)
                # 5. If the new individual has novel behaviour, add it to the population and the BD to the latent space
                if dominated == -1:                           #    If the individual did not dominate another individual
                    if novelty >= threshold:                  #    If the individual is novel
                        new_indiv.set_bd(new_bd.copy())
                        if len(pop) < UMAP_POPULATION_LIMIT:  #    Limit population for sake of memory 
                            pop.append(new_indiv)
                        else:
                            least_novel_indiv_index = np.argmin(np.sum(distance.cdist(images,images),1))
                            pop[least_novel_indiv_index] = new_indiv

                        # Increase curiosity score of individual
                        pop[index].increase_curiosity()

                    else:                                    #    If the individual is NOT novel
                        # Decrease curiosity score of individual
                        pop[index].decrease_curiosity()
                else:                                         #    If the individual dominated another individual
                    new_indiv.set_bd(new_bd.copy())
                    pop[dominated] = new_indiv

                    # Increase curiosity score of individual
                    pop[index].increase_curiosity()

        # 6. For each batch/generation, record various metrics
        current_klc_0, current_klc_1 = KLC(pop, comparison_gt)
        klc_log[0].append(current_klc_0)
        klc_log[1].append(current_klc_1)
        repertoire_size.append(len(pop))
        # rmse_log.append(np.mean(gen_rmse_log))


    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    print("Current Time =", current_time)

    plt.clf()
    plt.plot(klc_log[0], label="x")
    plt.plot(klc_log[1], label="y")
    plt.legend()
    plt.xlabel("Generation")
    plt.ylabel("KLC Score")
    title = "Kullback-Leibler Coverage, KL Divergence (Ground Truth || Generated BD)"
    plt.title(title)
    save_name = prefix + "/myplots/KLC"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_KLC.npy"
    np.save(np_name, klc_log)

    plt.clf()
    plt.plot(repertoire_size, label="Repertoire Size")
    plt.xlabel("Generation")
    plt.ylabel("Number of controllers")
    title = "Repertoire Size"
    plt.title(title)
    save_name = prefix + "/myplots/RepSize"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_repSize.npy"
    np.save(np_name, repertoire_size)
    
    plot_latent_gt(pop, -1, prefix)

    plt.clf()
    plt.plot(big_error_log[0], label="Training Loss")
    plt.plot(big_error_log[1], label="Validation Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Reconstruction Loss")
    plt.legend()
    title = "Reconstruction Loss"
    plt.title(title)
    save_name = prefix + "/myplots/Full_loss_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/pre_error_log.npy"
    np.save(np_name, big_error_log)

    # plt.clf()
    # plt.plot(rmse_log)
    # plt.xlabel("Generation")
    # plt.ylabel("RMSE Loss")
    # title = "Average Root Mean Squared Error per Generation"
    # plt.title(title)
    # save_name = prefix + "/myplots/pre_rmse_plot"
    # plt.savefig(save_name)
    # np_name = prefix + "/mydata/pre_rmse.npy"
    # np.save(np_name, rmse_log)



# Runs AURORA UMAP incremental version (i.e. with retraining periods)
def AURORA_incremental_UMAP(prefix):
    comparison_gt = np.load("GROUND_TRUTH.npy")
    # Randomly generate some controllers
    init_size = POPULATION_INITIAL_SIZE            # Initial size of population
    print("Creating population container")
    pop = [individual.indiv() for b in range(init_size)] # Container for training population
    print("Complete")

    # Collect sensory data of the generated controllers. In the case of the ballistic task this is the trajectories but any sensory data can be considered
    print("Evaluating current population")
    for member in pop:
        genotype = [random.uniform(FIT_MIN, FIT_MAX), random.uniform(FIT_MIN, FIT_MAX)]
        member.eval(genotype)
    print("Complete")

    # Create the dimension reduction algorithm (the UMAP)
    print("Creating UMAP")
    my_umap = cuUMAP(n_neighbors=50, n_epochs=500, spread=1.5, min_dist=.2, hash_input=False) 

    # Create container for latent space representation
    latent_space = []

    _max, _min = get_scaling_vars(pop)
    # Train and use the UMAP to get the behavioural descriptors
    images = np.squeeze(np.array([member.get_scaled_image(_max, _min) for member in pop]))
    member_bds = my_umap.fit_transform(images)
    member_bds = np.expand_dims(member_bds,axis=1)
    # Set BDs and fill latent space
    for member, member_bd in zip(pop, member_bds):
        member.set_bd(member_bd.copy())
        latent_space.append(member_bd.copy())
    
    # Record current latent space
    plot_latent_gt(pop, 0, prefix)

    # Calculate starting novelty threshold
    threshold = INITIAL_NOVELTY

    # These are needed for the main algorithm
    network_activation = 0
    klc_log = [[], []]
    just_finished_training = True
    roulette_wheel = []
    repertoire_size = []
    big_error_log = [ [] for i in range(2) ]
    # big_error_log[0] = t_error
    # big_error_log[1] = v_error

    # rmse_log = []

    last_run = False
    
    print("Starting Main AURORA Algorithm")
    # Main AURORA algorithm, for 5000 generations, run 200 evaluations, and retrain the network at specific generations
    for generation in range(NB_QD_BATCHES):
        print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))
        _max, _min = get_scaling_vars(pop)        
        if generation != 0 and generation % 100 == 0:
            print(klc_log[0][-1], klc_log[1][-1])
        if just_finished_training:
            print("Beginning QD iterations, next UMAP retraining at generation " + str(RETRAIN_ITER[network_activation]))
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print("Current Time =", current_time)
            print("Reinitialising curiosity proportionate roulette wheel")
        if last_run:
            print("Beginning QD iterations, no more UMAP training")
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            print("Current Time =", current_time)
            print("Reinitialising curiosity proportionate roulette wheel")
            last_run = False


        roulette_wheel = make_wheel(pop)
        x_squared, two_x, y_squared, two_y = make_novelty_params(pop)

        if generation % 50 == 0:
            print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))

        # Begin Quality Diversity iterations
        # gen_rmse_log = []
        for j in range(NB_QD_ITERATIONS):

            # 1. Select controller from population using curiosity proportionate selection ( AKA Spin wheel! )
            selector = random.uniform(0, 1)
            index = 0
            cumulative = roulette_wheel[index]
            while (selector >= cumulative ) and (index != len(roulette_wheel)-1):
                index += 1
                cumulative += roulette_wheel[index]
            this_indiv = pop[index]
            controller = this_indiv.get_key()

            # 2. Mutate and evaluate the chosen controller
            new_indiv = mut_eval(controller)
            if is_indiv_legal(new_indiv, this_indiv) == True:
                new_bd = None
                out = None
                image = None

                # 3. Get the Behavioural Descriptor for the new individual
                image = new_indiv.get_scaled_image(_max, _min)
                # GPU method does not allow for single point transform (k-nn algorithm) so run on whole dataset plus added point
                new_bd = np.expand_dims(my_umap.transform(np.append(images,image,0))[-1,:],0) 

                # out = my_umap.inverse_transform(new_bd)     #    Not supported on GPU version of UMAP 
                # gen_rmse_log.append(np.sqrt(np.mean((image - out)**2)))

                # 4. See if the new Behavioural Descriptor is novel enough

                novelty, dominated = calculate_novelty(new_bd, threshold, True, x_squared, two_x, y_squared, two_y, pop)
                # 5. If the new individual has novel behaviour, add it to the population and the BD to the latent space
                if dominated == -1:                           #    If the individual did not dominate another individual
                    if novelty >= threshold:                  #    If the individual is novel
                        new_indiv.set_bd(new_bd.copy())
                        if len(pop) < UMAP_POPULATION_LIMIT:  #    Limit population for sake of memory 
                            pop.append(new_indiv)
                        else:
                            least_novel_indiv_index = np.argmin(np.sum(distance.cdist(images,images),1))
                            pop[least_novel_indiv_index] = new_indiv

                        # Increase curiosity score of individual
                        pop[index].increase_curiosity()

                    else:                                    #    If the individual is NOT novel
                        # Decrease curiosity score of individual
                        pop[index].decrease_curiosity()
                else:                                         #    If the individual dominated another individual
                    new_indiv.set_bd(new_bd.copy())
                    pop[dominated] = new_indiv

                    # Increase curiosity score of individual
                    pop[index].increase_curiosity()


        just_finished_training = False

        # Check if this generation is before the last retraining session
        if network_activation < len(RETRAIN_ITER):
            if generation == RETRAIN_ITER[network_activation]:
                print("Finished QD iterations")
                now = datetime.now()
                current_time = now.strftime("%H:%M:%S")
                print("Current Time =", current_time)
                print("Current size of population is " + str(len(pop)))

                # 6. Retrain UMAP after a number of QD iterations
                print("Training UMAP, this is training session: " + str(network_activation + 2) + "/" + str(len(RETRAIN_ITER) + 1))
                _max, _min = get_scaling_vars(pop)
                images = np.squeeze(np.array([member.get_scaled_image(_max, _min) for member in pop]))
                member_bds = my_umap.fit_transform(images)
                member_bds = np.expand_dims(member_bds,1)
    
                print("Completed retraining")


                # 7. Clear latent space
                latent_space = []

                # 8. Assign the members of the population the new Behavioural Descriptors and refill the latent space
                _max, _min = get_scaling_vars(pop)
                for member, member_bd in zip(pop, member_bds):
                    member.set_bd(member_bd.copy())
                    latent_space.append(member_bd.copy())
                
                # 9. Calculate new novelty threshold to ensure population size less than 10000
                threshold = calculate_novelty_threshold(latent_space)
                print("New novelty threshold is " + str(threshold))

                # 10. Update population so that only members with novel bds are allowed
                print("Add viable members back to population")
                new_pop = []
                for member in pop:
                    this_bd = member.get_bd().copy()
                    novelty, dominated = grow_pop_calculate_novelty(this_bd, new_pop, threshold, True)
                    if dominated == -1:                           #    If the individual did not dominate another individual
                        if novelty >= threshold:                  #    If the individual is novel
                            new_pop.append(member)
                    else:                                         #    If the individual dominated another individual
                        new_pop[dominated] = member

                pop = new_pop
                print("After re-training, size of population is " + str(len(pop)))

                # 11. Get current Latent Space and Ground Truth plots
                plot_latent_gt(pop, generation, prefix)

                # 12. Prepare to check next retrain period
                network_activation += 1
                if network_activation == len(RETRAIN_ITER):
                    last_run = True
                else:
                    just_finished_training = True
            
        # 13. For each batch/generation, record various metrics
        current_klc_0, current_klc_1 = KLC(pop, comparison_gt)
        klc_log[0].append(current_klc_0)
        klc_log[1].append(current_klc_1)
        repertoire_size.append(len(pop))
        # rmse_log.append(np.mean(gen_rmse_log))

    plt.clf()
    plt.plot(klc_log[0], label="x")
    plt.plot(klc_log[1], label="y")
    plt.legend()
    plt.xlabel("Generation")
    plt.ylabel("KLC Score")
    title = "Kullback-Leibler Coverage, KL Divergence (Ground Truth || Generated BD)"
    plt.title(title)
    save_name = prefix + "/myplots/KLC"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_KLC.npy"
    np.save(np_name, klc_log)

    plt.clf()
    plt.plot(repertoire_size, label="Repertoire Size")
    plt.xlabel("Generation")
    plt.ylabel("Number of controllers")
    title = "Repertoire Size"
    plt.title(title)
    save_name = prefix + "/myplots/RepSize"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_repSize.npy"
    np.save(np_name, repertoire_size)
    
    plot_latent_gt(pop, -1, prefix)

    plt.clf()
    plt.plot(big_error_log[0], label="Training Loss")
    plt.plot(big_error_log[1], label="Validation Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Reconstruction Loss")
    plt.legend()
    title = "Reconstruction Loss"
    plt.title(title)
    save_name = prefix + "/myplots/Full_loss_plot"
    plt.savefig(save_name)
    np_name = prefix + "/mydata/inc_error_log.npy"
    np.save(np_name, big_error_log)

    # plt.clf()
    # plt.plot(rmse_log)
    # plt.xlabel("Generation")
    # plt.ylabel("RMSE Loss")
    # title = "Average Root Mean Squared Error per Generation"
    # plt.title(title)
    # save_name = prefix + "/myplots/inc_rmse_plot"
    # plt.savefig(save_name)
    # np_name = prefix + "/mydata/inc_rmse.npy"
    # np.save(np_name, rmse_log)
    


# __if__ hand_ver == True __then__ runs Handcoded version __else__ runs Genotype version
def Handcoded_Genotype(hand_ver, prefix):
    comparison_gt = np.load("GROUND_TRUTH.npy")

    #??Create population
    init_size = POPULATION_INITIAL_SIZE

    pop = []
    new_bd = np.zeros((1, 2))
    print("Creating population container")
    for b in range(init_size):
        new_indiv = individual.indiv()
        pop.append(new_indiv)
    print("Complete")
    print("Evaluating population container")
    latent_space = [ np.zeros((1,2)) for i in range(len(pop))]
    for m in range(len(pop)):
        genotype = [random.uniform(FIT_MIN, FIT_MAX), random.uniform(FIT_MIN, FIT_MAX)]
        pop[m].eval(genotype)
        if hand_ver == True:
            new_bd[0] = pop[m].get_gt()
        else:
            new_bd[0] = pop[m].get_key()
        pop[m].set_bd(new_bd.copy())
        latent_space[m][0] = new_bd.copy()
    print("Complete")

    klc_log = [[], []]
    roulette_wheel = []
    repertoire_size = []
    threshold = INITIAL_NOVELTY
    if hand_ver == False:
        threshold = calculate_novelty_threshold(latent_space)

    print_index = 0

    for generation in range(NB_QD_BATCHES):
        roulette_wheel = make_wheel(pop)
        x_squared, two_x, y_squared, two_y = make_novelty_params(pop)

        if print_index < len(PRINT_ITER):
            if generation == PRINT_ITER[print_index]:
                if hand_ver == True:
                    plot_gt(pop, generation, prefix)
                    print_index += 1
                else:
                    plot_latent_gt(pop, generation, prefix)
                    print_index += 1
        
        if generation != 0 and generation % 100 == 0:
            print(klc_log[0][-1], klc_log[1][-1])
        if generation % 50 == 0:
            print("Generation " + str(generation) + ", current size of population is " + str(len(pop)))
        # Begin Quality Diversity iterations

        for j in range(NB_QD_ITERATIONS):
            index = 0
            # 1. Select controller from population using curiosity proportionate selection
            selector = random.uniform(0, 1)
            cumulative = roulette_wheel[index]
            while (selector >= cumulative ) and (index != len(roulette_wheel)-1):
                index += 1
                cumulative += roulette_wheel[index]
            this_indiv = pop[index]

            controller = this_indiv.get_key()

            # 2. Mutate and evaluate the chosen controller
            new_indiv = mut_eval(controller)

            if is_indiv_legal(new_indiv, this_indiv) == True:
                # 3. Get new Behavioural Descriptor
                if hand_ver == True:
                    new_bd[0] = new_indiv.get_gt()
                else:
                    new_bd[0] = new_indiv.get_key()

                # 4. See if the new Behavioural Descriptor is novel enough
                novelty, dominated = calculate_novelty(new_bd, threshold, True, x_squared, two_x, y_squared, two_y, pop)
                # 5. If the new individual has novel behaviour, add it to the population and the BD to the latent space
                if dominated == -1:                           #    If the individual did not dominate another individual
                    if novelty >= threshold:                  #    If the individual is novel
                        new_indiv.set_bd(new_bd.copy())
                        pop.append(new_indiv)

                        # Increase curiosity score of individual
                        pop[index].increase_curiosity()

                    else:                                    #    If the individual is NOT novel
                        # Decrease curiosity score of individual
                        pop[index].decrease_curiosity()
                else:                                         #    If the individual dominated another individual
                    new_indiv.set_bd(new_bd.copy())
                    pop[dominated] = new_indiv

                    # Increase curiosity score of individual
                    pop[index].increase_curiosity()

        # 6. For each batch/generation, record various metrics
        current_klc_0, current_klc_1 = KLC(pop, comparison_gt)
        klc_log[0].append(current_klc_0)
        klc_log[1].append(current_klc_1)
        repertoire_size.append(len(pop))


    now = datetime.now()
    current_time = now.strftime("%H:%M:%S")
    print("Current Time =", current_time)

    plt.clf()
    plt.plot(klc_log[0], label="x")
    plt.plot(klc_log[1], label="y")
    plt.legend()
    plt.xlabel("Generation")
    plt.ylabel("KLC Score")
    title = "Kullback-Leibler Coverage, KL Divergence (Ground Truth || Generated BD)"
    plt.title(title)
    save_name = prefix + "/myplots/KLC"
    plt.savefig(save_name)
    if hand_ver == True:
        np_name = prefix + "/mydata/hand_KLC.npy"
        np.save(np_name, klc_log)
    else:
        np_name = prefix + "/mydata/geno_KLC.npy"
        np.save(np_name, klc_log)

    plt.clf()
    plt.plot(repertoire_size, label="Repertoire Size")
    plt.xlabel("Generation")
    plt.ylabel("Number of controllers")
    title = "Repertoire Size"
    plt.title(title)
    save_name = prefix + "/myplots/RepSize"
    plt.savefig(save_name)
    if hand_ver == True:
        np_name = prefix + "/mydata/hand_repSize.npy"
        np.save(np_name, repertoire_size)
    else:
        np_name = prefix + "/mydata/geno_repSize.npy"
        np.save(np_name, repertoire_size)

    if hand_ver == True:
        plot_gt(pop, -1, prefix)
    else: 
        plot_latent_gt(pop, -1, prefix)

# Generates GROUND TRUTH distribution used as reference to compare other distributions
def get_GROUND_TRUTH():
    dim = 300
    init_size = dim * dim           # Initial size of population
    pop = []                        # Container for population
    print("Creating population")
    for i in range(init_size):
        new_indiv = individual.indiv()
        pop.append(new_indiv)
    print("Complete")
    print("Evaluating population")
    step_size = (FIT_MAX - FIT_MIN)/dim
    genotype = [FIT_MIN, FIT_MIN]
    for member in pop:
        if genotype[1] > FIT_MAX:
            genotype[1] = FIT_MIN
            genotype[0] += step_size
        member.eval(genotype)
        genotype[1] += step_size
    print("Complete")

    for member in pop:
        member.set_bd(np.array(member.get_gt()))
    
    print("Add viable members back to population")
    new_pop = []
    count = 0
    random.shuffle(pop)
    met = int(len(pop)/100)
    for member in pop:
        if count % met == 0:
            print("At " + str(int(count/len(pop) * 100)) + "%, population is of size " + str(len(new_pop)))
        this_bd = member.get_bd()
        novelty, dominated = grow_pop_calculate_novelty(np.array(this_bd), new_pop, INITIAL_NOVELTY, True)
        if dominated == -1:                           #    If the individual did not dominate another individual
            if novelty >= INITIAL_NOVELTY:            #    If the individual is novel
                new_pop.append(member)
        else:                                         #    If the individual dominated another individual
            new_pop[dominated] = member
        count += 1

    pop = new_pop
    print("Size of distribution")
    print(len(pop))

    g_x = []
    g_y = []

    for member in pop:
        this_x, this_y = member.get_gt()
        g_x.append(this_x)
        g_y.append(this_y)
    
    np.save("GROUND_TRUTH.npy", np.array([g_x, g_y]))
    
    t = np.arange(len(pop))

    euclidean_from_zero_gt = []
    for i in range(len(g_x)):
        distance = g_x[i]**2 + g_y[i]**2
        euclidean_from_zero_gt.append(distance)


    g_x = [x for _,x in sorted(zip(euclidean_from_zero_gt, g_x))]
    g_y = [y for _,y in sorted(zip(euclidean_from_zero_gt, g_y))]

    plt.clf()
    plt.scatter(g_x, g_y, c=t, cmap="rainbow", s=1)
    plt.xlabel("X position at Max Height")
    plt.ylabel("Max Height Achieved")
    title = "The sampled ground truth distribution"
    plt.title(title)
    save_name = "Ground_Truth"
    plt.savefig(save_name)

def plot_runs(ver):
    prefix = "RUN_DATA/Genotype"
    np_name = prefix + "/mydata/geno_KLC.npy"
    geno_klc = np.load(np_name)
    np_name = prefix + "/mydata/geno_repSize.npy"
    geno_rep = np.load(np_name)

    prefix = "RUN_DATA/AURORA_PCA_pre"
    np_name = prefix + "/mydata/pre_KLC.npy"
    pca_pre_klc = np.load(np_name)
    np_name = prefix + "/mydata/pre_repSize.npy"
    pca_pre_rep = np.load(np_name)
    np_name = prefix + "/mydata/pre_rmse.npy"
    pca_pre_rmse = np.load(np_name)

    prefix = "RUN_DATA/AURORA_PCA_inc"
    np_name = prefix + "/mydata/inc_KLC.npy"
    pca_inc_klc = np.load(np_name)
    np_name = prefix + "/mydata/inc_repSize.npy"
    pca_inc_rep = np.load(np_name)
    np_name = prefix + "/mydata/inc_rmse.npy"
    pca_inc_rmse = np.load(np_name)

    prefix = "RUN_DATA/AURORA_AE_pre"
    np_name = prefix + "/mydata/pre_KLC.npy"
    ae_pre_klc = np.load(np_name)
    np_name = prefix + "/mydata/pre_repSize.npy"
    ae_pre_rep = np.load(np_name)
    np_name = prefix + "/mydata/pre_rmse.npy"
    ae_pre_rmse = np.load(np_name)

    prefix = "RUN_DATA/AURORA_AE_inc"
    np_name = prefix + "/mydata/inc_KLC.npy"
    ae_inc_klc = np.load(np_name)
    np_name = prefix + "/mydata/inc_repSize.npy"
    ae_inc_rep = np.load(np_name)
    np_name = prefix + "/mydata/inc_rmse.npy"
    ae_inc_rmse = np.load(np_name)

    prefix = "RUN_DATA/AURORA_VAE_pre"
    np_name = prefix + "/mydata/pre_KLC.npy"
    vae_pre_klc = np.load(np_name)
    np_name = prefix + "/mydata/pre_repSize.npy"
    vae_pre_rep = np.load(np_name)
    np_name = prefix + "/mydata/pre_rmse.npy"
    vae_pre_rmse = np.load(np_name)

    prefix = "RUN_DATA/AURORA_VAE_inc"
    np_name = prefix + "/mydata/inc_KLC.npy"
    vae_inc_klc = np.load(np_name)
    np_name = prefix + "/mydata/inc_repSize.npy"
    vae_inc_rep = np.load(np_name)
    np_name = prefix + "/mydata/inc_rmse.npy"
    vae_inc_rmse = np.load(np_name)

    prefix = "RUN_DATA/AURORA_UMAP_pre"
    np_name = prefix + "/mydata/pre_KLC.npy"
    umap_pre_klc = np.load(np_name)
    np_name = prefix + "/mydata/pre_repSize.npy"
    umap_pre_rep = np.load(np_name)

    prefix = "RUN_DATA/AURORA_UMAP_inc"
    np_name = prefix + "/mydata/inc_KLC.npy"
    umap_inc_klc = np.load(np_name)
    np_name = prefix + "/mydata/inc_repSize.npy"
    umap_inc_rep = np.load(np_name)


    # The KLC plots
    plt.clf()
    plt.plot(geno_klc[0], c = "k", label = "Genotype", alpha = 0.7)
    plt.plot(pca_pre_klc[0], c = "lightcoral", label = "AURORA-PCA Pretrained", alpha = 0.7)
    plt.plot(pca_inc_klc[0], c = "red", label = "AURORA-PCA Incremental", alpha = 0.7)
    plt.plot(ae_pre_klc[0], c = "m", label = "AURORA-AE Pretrained", alpha = 0.7)
    plt.plot(ae_inc_klc[0], color="plum", label = "AURORA-AE Incremental", alpha = 0.7)
    plt.plot(vae_pre_klc[0], color="aqua", label = "AURORA-VAE Pretrained", alpha = 0.7)
    plt.plot(vae_inc_klc[0], color="mediumturquoise", label = "AURORA-VAE Incremental", alpha = 0.7)
    plt.plot(umap_pre_klc[0], color="yellowgreen", label = "AURORA-UMAP Pretrained", alpha = 0.7)
    plt.plot(umap_inc_klc[0], color="greenyellow", label = "AURORA-UMAP Incremental", alpha = 0.7)

    plt.xlabel("Generation")
    plt.ylabel("KLC Score")
    title = "Kullback-Leibler Coverage Score of x Dimension per Generation"
    plt.title(title)
    lgd = plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    if ver == 1:
        plt.savefig("original_BIG_KLC_0", bbox_extra_artists=(lgd,), bbox_inches='tight')
    else:
        plt.savefig("extension_BIG_KLC_0", bbox_extra_artists=(lgd,), bbox_inches='tight')

    plt.clf()
    plt.plot(geno_klc[1], c = "k", label = "Genotype", alpha = 0.7)
    plt.plot(pca_pre_klc[1], c = "lightcoral", label = "AURORA-PCA Pretrained", alpha = 0.7)
    plt.plot(pca_inc_klc[1], c = "red", label = "AURORA-PCA Incremental", alpha = 0.7)
    plt.plot(ae_pre_klc[1], c = "m", label = "AURORA-AE Pretrained", alpha = 0.7)
    plt.plot(ae_inc_klc[1], color="plum", label = "AURORA-AE Incremental", alpha = 0.7)
    plt.plot(vae_pre_klc[1], color="aqua", label = "AURORA-VAE Pretrained", alpha = 0.7)
    plt.plot(vae_inc_klc[1], color="mediumturquoise", label = "AURORA-VAE Incremental", alpha = 0.7)
    plt.plot(umap_pre_klc[1], color="yellowgreen", label = "AURORA-UMAP Pretrained", alpha = 0.7)
    plt.plot(umap_inc_klc[1], color="greenyellow", label = "AURORA-UMAP Incremental", alpha = 0.7)
    
    plt.xlabel("Generation")
    plt.ylabel("KLC Score")
    title = "Kullback-Leibler Coverage Score of y Dimension per Generation"
    plt.title(title)
    lgd = plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    if ver == 1:
        plt.savefig("original_BIG_KLC_1", bbox_extra_artists=(lgd,), bbox_inches='tight')
    else:
        plt.savefig("extension_BIG_KLC_1", bbox_extra_artists=(lgd,), bbox_inches='tight')

    # The average KLC plot
    avg_geno_klc = []
    pca_avg_pre_klc = []
    pca_avg_inc_klc = []
    ae_avg_pre_klc = []
    ae_avg_inc_klc = []
    vae_avg_pre_klc = []
    vae_avg_inc_klc = []
    umap_avg_pre_klc = []
    umap_avg_inc_klc = []
    for  i in range(len(geno_klc[0])):
        tot = geno_klc[0][i] + geno_klc[1][i]
        avg_geno_klc.append(tot/2)
        tot = pca_pre_klc[0][i] + pca_pre_klc[1][i]
        pca_avg_pre_klc.append(tot/2)
        tot = pca_inc_klc[0][i] + pca_inc_klc[1][i]
        pca_avg_inc_klc.append(tot/2)
        tot = ae_pre_klc[0][i] + ae_pre_klc[1][i]
        ae_avg_pre_klc.append(tot/2)
        tot = ae_inc_klc[0][i] + ae_inc_klc[1][i]
        ae_avg_inc_klc.append(tot/2)
        tot = vae_pre_klc[0][i] + vae_pre_klc[1][i]
        vae_avg_pre_klc.append(tot/2)
        tot = vae_inc_klc[0][i] + vae_inc_klc[1][i]
        vae_avg_inc_klc.append(tot/2)
        tot = umap_pre_klc[0][i] + umap_pre_klc[1][i]
        umap_avg_pre_klc.append(tot/2)
        tot = umap_inc_klc[0][i] + umap_inc_klc[1][i]
        umap_avg_inc_klc.append(tot/2)
        

    plt.clf()
    plt.plot(avg_geno_klc, c = "k", label = "Genotype", alpha = 0.7)
    plt.plot(pca_avg_pre_klc, c = "lightcoral", label = "AURORA-PCA Pretrained", alpha = 0.7)
    plt.plot(pca_avg_inc_klc, c = "red", label = "AURORA-PCA Incremental", alpha = 0.7)
    plt.plot(ae_avg_pre_klc, c = "m", label = "AURORA-AE Pretrained", alpha = 0.7)
    plt.plot(ae_avg_inc_klc, color="plum", label = "AURORA-AE Incremental", alpha = 0.7)
    plt.plot(vae_avg_pre_klc, color="aqua", label = "AURORA-VAE Pretrained", alpha = 0.7)
    plt.plot(vae_avg_inc_klc, color="mediumturquoise", label = "AURORA-VAE Incremental", alpha = 0.7)
    plt.plot(umap_avg_pre_klc, color="yellowgreen", label = "AURORA-UMAP Pretrained", alpha = 0.7)
    plt.plot(umap_avg_inc_klc, color="greenyellow", label = "AURORA-UMAP Incremental", alpha = 0.7)
    
    plt.xlabel("Generation")
    plt.ylabel("Average KLC Score")
    title = "Average KLC Score (across dimensions) per Generation"
    plt.title(title)
    lgd = plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    if ver == 1:
        plt.savefig("original_avg_BIG_KLC", bbox_extra_artists=(lgd,), bbox_inches='tight')
    else:
        plt.savefig("extension_avg_BIG_KLC", bbox_extra_artists=(lgd,), bbox_inches='tight')

    # The Repertoire Size plot
    plt.clf()
    plt.plot(geno_rep, c = "k", label = "Genotype")
    plt.plot(pca_pre_rep, c = "lightcoral", label = "AURORA-PCA Pretrained")
    plt.plot(pca_inc_rep, c = "red", label = "AURORA-PCA Incremental")
    plt.plot(ae_pre_rep, c = "m", label = "AURORA-AE Pretrained")
    plt.plot(ae_inc_rep, color="plum", label = "AURORA-AE Incremental")
    plt.plot(vae_pre_rep, color="aqua", label = "AURORA-VAE Pretrained")
    plt.plot(vae_inc_rep, color="mediumturquoise", label = "AURORA-VAE Incremental")
    plt.plot(umap_pre_rep, color="yellowgreen", label = "AURORA-UMAP Pretrained")
    plt.plot(umap_inc_rep, color="greenyellow", label = "AURORA-UMAP Incremental")


    plt.xlabel("Generation")
    plt.ylabel("Repertoire Size")
    title = "Repertoire Size per Generation"
    plt.title(title)
    lgd = plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    if ver == 1:
        plt.savefig("original_BIG_REP", bbox_extra_artists=(lgd,), bbox_inches='tight')
    else:
        plt.savefig("extension_BIG_REP", bbox_extra_artists=(lgd,), bbox_inches='tight')

    # The RMSE plot
    plt.clf()
    plt.plot(pca_pre_rmse, c = "lightcoral", label = "AURORA-PCA Pretrained", alpha = 0.7)
    plt.plot(pca_inc_rmse, c = "red", label = "AURORA-PCA Incremental", alpha = 0.7)
    plt.plot(ae_pre_rmse, c = "m", label = "AURORA-AE Pretrained", alpha = 0.7)
    plt.plot(ae_inc_rmse, color="plum", label = "AURORA-AE Incremental", alpha = 0.7)
    plt.plot(vae_pre_rmse, color="aqua", label = "AURORA-VAE Pretrained", alpha = 0.7)
    plt.plot(vae_inc_rmse, color="mediumturquoise", label = "AURORA-VAE Incremental", alpha = 0.7)

    plt.xlabel("Generation")
    plt.ylabel("RMS Error")
    title = "Reconstruction Error per Generation"
    plt.title(title)
    lgd = plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    if ver == 1:
        plt.savefig("original_BIG_RMSE", bbox_extra_artists=(lgd,), bbox_inches='tight')
    else:
        plt.savefig("extension_BIG_RMSE", bbox_extra_artists=(lgd,), bbox_inches='tight')

    i = 49
    pca_pre_avg_rmse = [ 0 for x in range(i) ]
    pca_inc_avg_rmse = [ 0 for x in range(i) ]
    ae_pre_avg_rmse = [ 0 for x in range(i) ]
    ae_inc_avg_rmse = [ 0 for x in range(i) ]
    vae_pre_avg_rmse = [ 0 for x in range(i) ]
    vae_inc_avg_rmse = [ 0 for x in range(i) ]


    pca_pre_ex_avg_klc = [ 0 for x in range(i) ]
    pca_inc_ex_avg_klc = [ 0 for x in range(i) ]
    ae_pre_ex_avg_klc = [ 0 for x in range(i) ]
    ae_inc_ex_avg_klc = [ 0 for x in range(i) ]
    vae_pre_ex_avg_klc = [ 0 for x in range(i) ]
    vae_inc_ex_avg_klc = [ 0 for x in range(i) ]
    geno_ex_avg_klc = [ 0 for x in range(i) ]

    for index in range(4950):
        pca_pre_avg_rmse.append(np.mean(pca_pre_rmse[index : index + 50]))
        pca_inc_avg_rmse.append(np.mean(pca_inc_rmse[index : index + 50]))
        ae_pre_avg_rmse.append(np.mean(ae_pre_rmse[index : index + 50]))
        ae_inc_avg_rmse.append(np.mean(ae_inc_rmse[index : index + 50]))
        vae_pre_avg_rmse.append(np.mean(vae_pre_rmse[index : index + 50]))
        vae_inc_avg_rmse.append(np.mean(vae_inc_rmse[index : index + 50]))

        pca_pre_ex_avg_klc.append(np.mean(pca_avg_pre_klc[index : index + 50]))
        pca_inc_ex_avg_klc.append(np.mean(pca_avg_inc_klc[index : index + 50]))
        ae_pre_ex_avg_klc.append(np.mean(ae_avg_pre_klc[index : index + 50]))
        ae_inc_ex_avg_klc.append(np.mean(ae_avg_inc_klc[index : index + 50]))
        vae_pre_ex_avg_klc.append(np.mean(vae_avg_pre_klc[index : index + 50]))
        vae_inc_ex_avg_klc.append(np.mean(vae_avg_inc_klc[index : index + 50]))
        geno_ex_avg_klc.append(np.mean(avg_geno_klc[index : index + 50]))
    
    plt.clf()
    plt.plot(pca_pre_avg_rmse, c = "lightcoral", label = "AURORA-PCA Pretrained", alpha = 0.7)
    plt.plot(pca_inc_avg_rmse, c = "red", label = "AURORA-PCA Incremental", alpha = 0.7)
    plt.plot(ae_pre_avg_rmse, c = "m", label = "AURORA-AE Pretrained", alpha = 0.7)
    plt.plot(ae_inc_avg_rmse, color="plum", label = "AURORA-AE Incremental", alpha = 0.7)
    plt.plot(vae_pre_avg_rmse, color="aqua", label = "AURORA-VAE Pretrained", alpha = 0.7)
    plt.plot(vae_inc_avg_rmse, color="mediumturquoise", label = "AURORA-VAE Incremental", alpha = 0.7)
    
    plt.xlabel("Generation")
    plt.ylabel("Average RMS Error")
    plt.xlim(50, 5000)
    title = "Reconstruction Error Averaged across Last 50 Generations"
    plt.title(title)
    lgd = plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    if ver == 1:
        plt.savefig("original_BIG_AVG_RMSE", bbox_extra_artists=(lgd,), bbox_inches='tight')
    else:
        plt.savefig("extension_BIG_AVG_RMSE", bbox_extra_artists=(lgd,), bbox_inches='tight')

    plt.clf()
    
    plt.plot(geno_ex_avg_klc, c = "k", label = "Genotype", alpha=0.7)
    plt.plot(pca_pre_ex_avg_klc, c = "lightcoral", label = "AURORA-PCA Pretrained", alpha = 0.7)
    plt.plot(pca_inc_ex_avg_klc, c = "red", label = "AURORA-PCA Incremental", alpha = 0.7)
    plt.plot(ae_pre_ex_avg_klc, c = "m", label = "AURORA-AE Pretrained", alpha=0.7)
    plt.plot(ae_inc_ex_avg_klc, c = "plum", label = "AURORA-AE Incremental", alpha=0.7)
    plt.plot(vae_pre_ex_avg_klc, color="aqua", label = "AURORA-VAE Pretrained", alpha = 0.7)
    plt.plot(vae_inc_ex_avg_klc, color="mediumturquoise", label = "AURORA-VAE Incremental", alpha = 0.7)
    plt.xlabel("Generation")
    plt.ylabel("Average KLC Score across dimensions")
    plt.xlim(50, 5000)
    title = "Average KLC Score Averaged across Last 50 Generations"
    plt.title(title)
    lgd = plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    if ver == 1:
        plt.savefig("original_BIG_EX_AVG_KLC", bbox_extra_artists=(lgd,), bbox_inches='tight')
    else:
        plt.savefig("extension_BIG_EX_AVG_KLC", bbox_extra_artists=(lgd,), bbox_inches='tight')

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', type=str, default='null', help = "Which version of AURORA-AE do you want to run? 'incremental' or 'pretrained'?")
    parser.add_argument('--plot_runs', type=int, default=0, help = "Do you want to plot the results of all the algorithms? '0' for no, '1' for yes")
    parser.add_argument('--num_epochs', type=int, default=500, help = "How many epochs do you want to run training for?")
    
    args = parser.parse_args()

    
    if args.plot_runs == 1:
        plot_runs(1)

    if args.version == "pretrainedPCA":
        prefix = None   
        print("STARTING PRETRAINED VERSION")
        prefix = "RUN_DATA/AURORA_PCA_pre"
        NUM_EPOCH = args.num_epochs
        AURORA_pretrained_PCA(prefix)
    elif args.version == "incrementalPCA":  
        prefix = None  
        print("STARTING INCREMENTAL VERSION")
        prefix = "RUN_DATA/AURORA_PCA_inc"
        NUM_EPOCH = args.num_epochs
        AURORA_incremental_PCA(prefix)
    elif args.version == "pretrainedAE":
        prefix = None   
        print("STARTING PRETRAINED VERSION")
        prefix = "RUN_DATA/AURORA_AE_pre"
        NUM_EPOCH = args.num_epochs
        AURORA_pretrained_VAE(prefix,False)
    elif args.version == "incrementalAE":  
        prefix = None  
        print("STARTING INCREMENTAL VERSION")
        prefix = "RUN_DATA/AURORA_AE_inc"
        NUM_EPOCH = args.num_epochs
        AURORA_incremental_VAE(prefix,False)
    elif args.version == "pretrainedVAE":
        prefix = None   
        print("STARTING PRETRAINED VERSION")
        prefix = "RUN_DATA/AURORA_VAE_pre"
        NUM_EPOCH = args.num_epochs
        AURORA_pretrained_VAE(prefix,True)
    elif args.version == "incrementalVAE":  
        prefix = None  
        print("STARTING INCREMENTAL VERSION")
        prefix = "RUN_DATA/AURORA_VAE_inc"
        NUM_EPOCH = args.num_epochs
        AURORA_incremental_VAE(prefix,True)
    if args.version == "pretrainedUMAP":
        prefix = None   
        print("STARTING PRETRAINED VERSION")
        prefix = "RUN_DATA/AURORA_UMAP_pre"
        NUM_EPOCH = args.num_epochs
        AURORA_pretrained_UMAP(prefix)
    elif args.version == "incrementalUMAP":  
        prefix = None  
        print("STARTING INCREMENTAL VERSION")
        prefix = "RUN_DATA/AURORA_UMAP_inc"
        NUM_EPOCH = args.num_epochs
        AURORA_incremental_UMAP(prefix)
    elif args.version == "handcoded":
        print("STARTING HANDCODED")
        prefix = "RUN_DATA/Handcoded"
        Handcoded_Genotype(True, prefix)
    elif args.version == "genotype":
        print("STARTING GENOTYPE")
        prefix = "RUN_DATA/Genotype"
        Handcoded_Genotype(False, prefix)
    elif args.version == "GT":
        print("GENERATE REFERENCE GROUND TRUTH DISTRIBUTION")
        get_GROUND_TRUTH()
print("OVERALL RUN TIME --- %s seconds ---" % (time.time() - start_time))