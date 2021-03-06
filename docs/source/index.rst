========================================================================
DeepCpG: Deep neural networks for predicting single-cell DNA methylation
========================================================================

DeepCpG is a deep neural network for predicting the methylation state of CpG dinucleotides in multiple cells. It allows to accurately impute incomplete DNA methylation profiles, to discover predictive sequence motifs, and to quantify the effect of sequence mutations. (`Angermueller et al, 2017 <http://biorxiv.org/content/early/2017/02/01/055715>`_).

::

  Angermueller, Christof, Heather Lee, Wolf Reik, and Oliver Stegle. Accurate Prediction of Single-Cell DNA Methylation States Using Deep Learning. http://biorxiv.org/content/early/2017/02/01/055715 bioRxiv, February 1, 2017, 55715. doi:10.1101/055715.


Installation
============

The easiest way to install DeepCpG is to use ``PyPI``:

.. code:: bash

  pip install deepcpg

Alternatively, you can checkout the repository

.. code:: bash

  git clone https://github.com/cangermueller/deepcpg.git


and then install DeepCpG using ``setup.py``:

.. code:: bash

  python setup.py install


Examples
========

Interactive examples on how to use DeepCpG can be found `here <https://github.com/cangermueller/deepcpg/tree/master/examples>`_.


Documentation
=============

* :ref:`train` -- Everything about model training.
* :ref:`modules` -- Description of DNA, CpG, and joint module architectures.
* :ref:`libdoc` -- Documentation of DeepCpG source code.


Indices and tables
==================
* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


.. toctree::
  :maxdepth: 1
  :hidden:

  train
  modules
  lib/index
