# Copyright (c) 2022 Yichi Zhang. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import torch
import torch.nn as nn
import torch.nn.functional as F

from ..layers.graphlearn import GraphLearner
from ..layers.gnn import GCN, GAT
from ..utils.generic_utils import to_cuda, normalize_adj
from ..utils.constants import VERY_SMALL_NUMBER



class GraphClf(nn.Module):
    def __init__(self, config):
        super(GraphClf, self).__init__()
        self.config = config
        self.name = 'GraphClf'
        self.graph_learn = config['graph_learn']
        self.graph_metric_type = config['graph_metric_type']
        self.graph_module = config['graph_module']
        self.device = config['device']
        nfeat = config['num_feat']
        nclass = config['num_class']
        hidden_size = config['hidden_size']
        self.dropout = config['dropout']
        self.graph_skip_conn = config['graph_skip_conn']
        self.graph_include_self = config.get('graph_include_self', True)


        if self.graph_module == 'gcn':
            self.encoder = GCN(nfeat=nfeat,
                                nhid=hidden_size,
                                nclass=nclass,
                                dropout=self.dropout)

        else:
            raise RuntimeError('Unknown graph_module: {}'.format(self.graph_module))


        if self.graph_learn:
            self.graph_learner = GraphLearner(nfeat, config['graph_learn_hidden_size'],
                                            topk=config['graph_learn_topk'],
                                            epsilon=config['graph_learn_epsilon'],
                                            num_pers=config['graph_learn_num_pers'],
                                            metric_type=config['graph_metric_type'],
                                            device=self.device)


            self.graph_learner2 = GraphLearner(hidden_size,
                                            config.get('graph_learn_hidden_size2', config['graph_learn_hidden_size']),
                                            topk=config.get('graph_learn_topk2', config['graph_learn_topk']),
                                            epsilon=config.get('graph_learn_epsilon2', config['graph_learn_epsilon']),
                                            num_pers=config['graph_learn_num_pers'],
                                            metric_type=config['graph_metric_type'],
                                            device=self.device)

            print('[ Graph Learner ]')

            if config['graph_learn_regularization']:
              print('[ Graph Regularization]')
        else:
            self.graph_learner = None
            self.graph_learner2 = None

    def learn_graph(self, graph_learner, node_features, graph_skip_conn, graph_include_self=False, init_adj=None):
        if self.graph_learn:
            raw_adj = graph_learner(node_features)

            if self.graph_metric_type in ('kernel', 'weighted_cosine'):
                assert raw_adj.min().item() >= 0
                # adj = (raw_adj > 0).float()
                # adj = normalize_adj(adj)
                adj = raw_adj / torch.clamp(torch.sum(raw_adj, dim=-1, keepdim=True), min=VERY_SMALL_NUMBER)
            elif self.graph_metric_type == 'cosine':
                adj = (raw_adj > 0).float()
                adj = normalize_adj(adj)
            else:
                adj = torch.softmax(raw_adj, dim=-1)

            if graph_skip_conn in (0, None):
                if graph_include_self:
                    adj = adj + to_cuda(torch.eye(adj.size(0)), self.device)
            else:
                adj = graph_skip_conn * init_adj + (1 - graph_skip_conn) * adj
                # adj = (raw_adj > 0).float()
                # adj = normalize_adj(raw_adj)
        else:
            raw_adj = None
            adj = init_adj
        return raw_adj, adj


    def forward(self, node_features, init_adj=None):
        node_features = F.dropout(node_features, self.config.get('feat_adj_dropout', 0), training=self.training)
        raw_adj, adj = self.learn_graph(self.graph_learner, node_features, self.graph_skip_conn, init_adj=init_adj)
        adj = F.dropout(adj, self.config.get('feat_adj_dropout', 0), training=self.training)
        node_vec = self.encoder(node_features, adj)
        output = F.log_softmax(node_vec, dim=-1)
        return output, adj

