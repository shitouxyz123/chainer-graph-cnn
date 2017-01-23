"""
Based on:
https://github.com/mdeff/cnn_graph/blob/master/lib/coarsening.py
"""
import numpy as np
import scipy.sparse


def coarsen(A, levels, self_connections=False):
    """
    Coarsen a graph, represented by its adjacency matrix A, at multiple
    levels.
    """
    graphs, parents, pooling_inds, = metis(A, levels)
    return graphs, pooling_inds

    #perms = compute_perm(parents)

    #for i, A in enumerate(graphs):
    #    M, M = A.shape

    #    if not self_connections:
    #        A = A.tocoo()
    #        A.setdiag(0)

    #    if i < levels:
    #        A = perm_adjacency(A, perms[i])

    #    A = A.tocsr()
    #    A.eliminate_zeros()
    #    graphs[i] = A

    #    Mnew, Mnew = A.shape
    #    print('Layer {0}: M_{0} = |V| = {1} nodes ({2} added),'
    #          '|E| = {3} edges'.format(i, Mnew, Mnew-M, A.nnz//2))

    #return graphs, perms[0] if levels > 0 else None


def metis(W, levels):
    """
    Coarsen a graph multiple times using the METIS algorithm.

    INPUT
    W: symmetric sparse weight (adjacency) matrix
    levels: the number of coarsened graphs

    OUTPUT
    graph[0]: original graph of size N_1
    graph[2]: coarser graph of size N_2 < N_1
    graph[levels]: coarsest graph of Size N_levels < ... < N_2 < N_1
    parents[i] is a vector of size N_i with entries ranging from 1 to N_{i+1}
        which indicate the parents in the coarser graph[i+1]

    NOTE
    if "graph" is a list of length k, then "parents" will be a list of length k-1
    """

    # Performs only the coarsening part of Graclus (not the subsequent refinement clustering step)

    N, N = W.shape
    degree = W.sum(axis=0) # assume diagonal elements are zero
    rid = np.random.permutation(range(N)) # The order in which to visit the vertices
    parents = []
    pooling_inds = []
    graphs = []
    graphs.append(W)

    for _ in range(levels):

        weights = degree            # graclus weights
        weights = np.array(weights).squeeze()

        # PAIR THE VERTICES AND CONSTRUCT THE ROOT VECTOR
        idx_row, idx_col, val = scipy.sparse.find(W)
        perm = np.argsort(idx_row)
        rr = idx_row[perm]
        cc = idx_col[perm]
        vv = val[perm]
        cluster_id, pooling_ind = metis_one_level(rr,cc,vv,rid,weights)  # rr is ordered
        parents.append(cluster_id)
        pooling_inds.append(pooling_ind)

        # COMPUTE THE EDGES WEIGHTS FOR THE NEW GRAPH
        nrr = cluster_id[rr]
        ncc = cluster_id[cc]
        nvv = vv
        Nnew = cluster_id.max() + 1
        # CSR is more appropriate: row,val pairs appear multiple times
        W = scipy.sparse.csr_matrix((nvv,(nrr,ncc)), shape=(Nnew,Nnew)) # weights of merged vertices are summed here
        W.eliminate_zeros()
        # Add new graph to the list of all coarsened graphs
        graphs.append(W)
        N, N = W.shape

        # COMPUTE THE DEGREE
        degree = W.sum(axis=0)

        # For the new graph, visit the vertices in order of smallest degree first
        ss = np.array(W.sum(axis=0)).squeeze()
        rid = np.argsort(ss)

    return graphs, parents, pooling_inds


# Coarsen a graph given by rr,cc,vv.  rr is assumed to be ordered
def metis_one_level(rr,cc,vv,rid,weights):
    # rr,cc,vv are the rows,cols,values corresponding to non-zero entries
    # weights: weight of each vertex. For the normalized cut case, the weight of each vertex is its degree

    nnz = rr.shape[0]
    N = rr[nnz-1] + 1

    marked = np.zeros(N, np.bool)
    rowstart = np.zeros(N, np.int32) # the index of the start of each row
    rowlength = np.zeros(N, np.int32) # the number of nonzero elements on each row
    cluster_id = np.zeros(N, np.int32) # result: The id of each cluster that a vertex belongs to
    pooling_ind = []

    oldval = rr[0]
    count = 0

    # calculate the number of elements on each row
    for ii in range(nnz):
        rowlength[count] = rowlength[count] + 1
        if rr[ii] > oldval:
            oldval = rr[ii]
            rowstart[count+1] = ii
            count = count + 1

    clustercount = 0
    for ii in range(N): # for each vertex
        tid = rid[ii] # in the order given by rid
        if not marked[tid]:
            marked[tid] = True # mark the vertex so that we don't visit it again
            wmax = 0.0
            rs = rowstart[tid]
            bestneighbor = -1
            for jj in range(rowlength[tid]):
                nid = cc[rs+jj] # check each neighbor
                if marked[nid]:
                    tval = 0.0
                else:
                    tval = vv[rs+jj] * (1.0/weights[tid] + 1.0/weights[nid]) # the weight between the vertices multiplied by the inverse degrees
                if tval > wmax:
                    wmax = tval
                    bestneighbor = nid

            cluster_id[tid] = clustercount

            if bestneighbor > -1:
                cluster_id[bestneighbor] = clustercount
                marked[bestneighbor] = True
                pooling_ind.append((tid, bestneighbor))
            else:
                pooling_ind.append((tid, tid)) # if singleton vertex, always pool with itself in order to keep the vertex

            # note that the vertex will not be merged if it had no neighbors (but will belong to a singleton cluster)

            clustercount += 1

    return cluster_id, pooling_ind

def compute_perm(parents):
    """
    Return a list of indices to reorder the adjacency and data matrices so
    that the union of two neighbors from layer to layer forms a binary tree.
    """

    # Order of last layer is random (chosen by the clustering algorithm).
    indices = []
    if len(parents) > 0:
        M_last = max(parents[-1]) + 1
        indices.append(list(range(M_last)))

    for parent in parents[::-1]:
        #print('parent: {}'.format(parent))

        # Fake nodes go after real ones.
        pool_singeltons = len(parent)

        indices_layer = []
        for i in indices[-1]:
            indices_node = list(np.where(parent == i)[0])
            assert 0 <= len(indices_node) <= 2
            #print('indices_node: {}'.format(indices_node))

            # Add a node to go with a singelton.
            if len(indices_node) is 1:
                indices_node.append(pool_singeltons)
                pool_singeltons += 1
                #print('new singelton: {}'.format(indices_node))
            # Add two nodes as children of a singelton in the parent.
            elif len(indices_node) is 0:
                indices_node.append(pool_singeltons+0)
                indices_node.append(pool_singeltons+1)
                pool_singeltons += 2
                #print('singelton childrens: {}'.format(indices_node))

            indices_layer.extend(indices_node)
        indices.append(indices_layer)

    # Sanity checks.
    for i,indices_layer in enumerate(indices):
        M = M_last*2**i
        # Reduction by 2 at each layer (binary tree).
        assert len(indices[0] == M)
        # The new ordering does not omit an indice.
        assert sorted(indices_layer) == list(range(M))

    return indices[::-1]

assert (compute_perm([np.array([4,1,1,2,2,3,0,0,3]),np.array([2,1,0,1,0])])
        == [[3,4,0,9,1,2,5,8,6,7,10,11],[2,4,1,3,0,5],[0,1,2]])

def perm_data(x, indices):
    """
    Permute data matrix, i.e. exchange node ids,
    so that binary unions form the clustering tree.
    """
    if indices is None:
        return x

    N, M = x.shape
    Mnew = len(indices)
    assert Mnew >= M
    xnew = np.empty((N, Mnew))
    for i,j in enumerate(indices):
        # Existing vertex, i.e. real data.
        if j < M:
            xnew[:,i] = x[:,j]
        # Fake vertex because of singeltons.
        # They will stay 0 so that max pooling chooses the singelton.
        # Or -infty ?
        else:
            xnew[:,i] = np.zeros(N)
    return xnew

def perm_adjacency(A, indices):
    """
    Permute adjacency matrix, i.e. exchange node ids,
    so that binary unions form the clustering tree.
    """
    if indices is None:
        return A

    M, M = A.shape
    Mnew = len(indices)
    assert Mnew >= M
    A = A.tocoo()

    # Add Mnew - M isolated vertices.
    if Mnew > M:
        rows = scipy.sparse.coo_matrix((Mnew-M,    M), dtype=np.float32)
        cols = scipy.sparse.coo_matrix((Mnew, Mnew-M), dtype=np.float32)
        A = scipy.sparse.vstack([A, rows])
        A = scipy.sparse.hstack([A, cols])

    # Permute the rows and the columns.
    perm = np.argsort(indices)
    A.row = np.array(perm)[A.row]
    A.col = np.array(perm)[A.col]

    # assert np.abs(A - A.T).mean() < 1e-9
    assert type(A) is scipy.sparse.coo.coo_matrix
    return A
