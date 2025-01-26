#include <Python.h>
#define NPY_NO_DEPRECATED_API NPY_1_9_API_VERSION
#include "numpy/arrayobject.h"

#ifdef HAVE_BLAS_ILP64
#define F_INT npy_int64
#define F_INT_NPY NPY_INT64
#else
#define F_INT int
#define F_INT_NPY NPY_INT
#endif

typedef struct _dassl_globals {
    PyObject *python_function;
    int neqn;
} dassl_params;

static dassl_params global_dassl_params = {NULL, 0};

#if defined(UPPERCASE_FORTRAN)
    #if defined(NO_APPEND_FORTRAN)
        /* nothing to do here */
    #else
        #define DDASSL  DDASSL_
    #endif
#else
    #if defined(NO_APPEND_FORTRAN)
        #define DDASSL  ddassl
    #else
        #define DDASSL  ddassl_
    #endif
#endif

typedef void dassl_f_t(double *t, double *y, double *ydot, 
                         double *f, F_INT *ires, 
                         double *rpar, F_INT *ipar);
typedef void dassl_jac_t(double *t, double *y, double *ydot, 
                         double *J, double* cj, 
                         double *rpar, F_INT *ipar);

void DDASSL(dassl_f_t *res, F_INT *neq, double *t, 
           double *y, double *yp, double *tout, 
           F_INT *info, double *rtol, double *atol,
           F_INT *idid, double *rwork, F_INT *lrw,
           F_INT *iwork, F_INT *liw, double *rpar, 
           F_INT *ipar);

void dassl_f(double *t, double *y, double *yp, 
             double *f, F_INT *ierr, 
             double *rpar, F_INT *ipar)
{
    PyObject *y_obj = NULL;
    PyObject *yp_obj = NULL;
    PyObject *result = NULL;
    PyObject *arglist = NULL;
    PyArrayObject *result_array = NULL;

    npy_intp dims[1];
    dims[0] = global_dassl_params.neqn;

    /* Build numpy arrays from y and yp. */
    y_obj = PyArray_SimpleNewFromData(1, dims, NPY_DOUBLE, y);
    if (y_obj == NULL) {
        PyErr_SetString(PyExc_ValueError, "PyArray_SimpleNewFromData(1, dims, NPY_DOUBLE, y) failed.");
        goto fail;
    }
    yp_obj = PyArray_SimpleNewFromData(1, dims, NPY_DOUBLE, yp);
    if (yp_obj == NULL) {
        PyErr_SetString(PyExc_ValueError, "PyArray_SimpleNewFromData(1, dims, NPY_DOUBLE, yp) failed.");
        goto fail;
    }

    /* Build argument list. */
    arglist = Py_BuildValue(
        "dOO",
        *t,
        y_obj,
        yp_obj
    );
    if (arglist == NULL) {
        PyErr_SetString(PyExc_ValueError, "Py_BuildValue failed.");
        goto fail;
    }

    /* Call the Python function. */
    result = PyObject_CallObject(global_dassl_params.python_function, arglist);
    if (result == NULL) {
        PyErr_SetString(PyExc_ValueError, "PyObject_CallObject(global_dassl_params.python_function, arglist) failed.");
        goto fail;
    }

    /* Build numpy array from result and copy to f. */
    result_array = (PyArrayObject *) PyArray_ContiguousFromObject(result, NPY_DOUBLE, 0, 0);
    if (result_array == NULL) {
        PyErr_SetString(PyExc_ValueError, "PyArray_ContiguousFromObject(result, NPY_DOUBLE, 0, 0) failed.");
        goto fail;
    }

    /* Copy data from the result array to your C array */
    memcpy(f, PyArray_DATA(result_array), PyArray_NBYTES(result_array));

    fail:
        Py_XDECREF(y_obj);
        Py_XDECREF(yp_obj);
        Py_XDECREF(result);
        Py_XDECREF(arglist);
        Py_XDECREF(result_array);
        return;
}


void dassl_jac(F_INT ldj, F_INT neqn, F_INT nlj, F_INT nuj, 
             double *t, double *y, double *ydot, double *J, 
             double *rpar, F_INT *ipar){}

static PyObject* dassl(PyObject *self, PyObject *args, PyObject *kwargs)
{
    PyObject *f_obj = NULL;
    PyObject *J_obj = Py_None;
    PyObject *t_span_obj = NULL;
    PyObject *y_obj = NULL;
    PyObject *yp_obj = NULL;
    PyObject *order_sol;
    PyObject *t_sol;
    PyObject *y_sol;
    PyObject *yp_sol;
    PyArrayObject *y_array = NULL;
    PyArrayObject *yp_array = NULL;

    double rtol = 1.0e-3;
    double atol = 1.0e-6;
    double t, t1;
    double *y, *yp;

    int success = 1;

    int neqn;
    int jnum;
    int ninfo = 15;

    int lrwork;
    int liwork;
    double *rwork;
    int *iwork;
    int *info;

    double *rpar;
    int *ipar;
    int idid;

    // parse inputs
    static char *kwlist[] = {"f", "t_span", "y0", "yp0", // mandatory arguments
                             "rtol", "atol", "J", NULL}; // optional arguments and NULL termination
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "OOOO|ddOOO", kwlist, 
                                     &f_obj, &t_span_obj, &y_obj, &yp_obj, // positional arguments
                                     &rtol, &atol, &J_obj)) // optional arguments
        return NULL;

    // check if function and Jacobians (if present) are callable
    if (!PyCallable_Check(f_obj)) {
        PyErr_SetString(PyExc_ValueError, "`f` must be a callable function.");
    }
    if (J_obj != Py_None) {
        if (!PyCallable_Check(J_obj)) {
            PyErr_SetString(PyExc_ValueError, "`J` must be a callable function.");
        }
        jnum = 1;
        PyErr_SetString(PyExc_ValueError, "User-defined Jacobian `J` is not implemented yet.");
    } else {
        jnum = 0; 
    }

    // unpack t_span tuple
    PyArg_ParseTuple(t_span_obj, "dd", &t, &t1);
    if (!(t1 > t)) {
        PyErr_SetString(PyExc_ValueError, "`t1` must larger than `t0`.");
    }

    // initial conditions
    y_array = (PyArrayObject *) PyArray_ContiguousFromObject(y_obj, NPY_DOUBLE, 0, 0);
    if (y_array == NULL) {
        PyErr_SetString(PyExc_ValueError, "PyArray_ContiguousFromObject(y_obj, NPY_DOUBLE, 0, 0) failed");
        goto fail;
    }
    if (PyArray_NDIM(y_array) > 1) {
        PyErr_SetString(PyExc_ValueError, "Initial condition y0 must be one-dimensional.");
        goto fail;
    }
    y = (double *) PyArray_DATA(y_array);
    neqn = PyArray_Size((PyObject *) y_array);

    yp_array = (PyArrayObject *) PyArray_ContiguousFromObject(yp_obj, NPY_DOUBLE, 0, 0);
    if (yp_array == NULL) {
        PyErr_SetString(PyExc_ValueError, "PyArray_ContiguousFromObject(yp_obj, NPY_DOUBLE, 0, 0) failed");
        goto fail;
    }
    if (PyArray_NDIM(yp_array) > 1) {
        PyErr_SetString(PyExc_ValueError, "Initial condition yp0 must be one-dimensional.");
        goto fail;
    }
    yp = (double *) PyArray_DATA(yp_array);
    if (!(neqn == PyArray_Size((PyObject *) yp_array))) {
        PyErr_SetString(PyExc_ValueError, "Size of y0 and yp0 have to coincide.");
        goto fail;
    }

    // initialize iwork and rwork
    lrwork = 40 + (5 + 4) * neqn + pow(neqn, 2);
    liwork = 20 + neqn;

    rwork = malloc(lrwork * sizeof(double));
    iwork = malloc(liwork * sizeof(int));

    for (int i=0; i<20; i++) {
        iwork[i] = 0;
        rwork[i] = 0.0;
    }

    // initialize info
    info = malloc(ninfo * sizeof(int));
    for (int i=0; i<ninfo; i++) {
        info[i] = 0;
    }
    // get intermediate results
    info[2] = 1;
    // numerical jacobian
    info[5] = jnum;

    // set global_dassl_params
    global_dassl_params.neqn = neqn;
    global_dassl_params.python_function = f_obj;

    // store solution in python list and start with initial values
    order_sol = PyList_New(0);
    t_sol = PyList_New(0);
    y_sol = PyList_New(0);
    yp_sol = PyList_New(0);
    PyList_Append(order_sol, PyLong_FromLong(1));
    PyList_Append(t_sol, PyFloat_FromDouble(t));
    PyList_Append(y_sol, PyArray_NewCopy(y_array, NPY_ANYORDER));
    PyList_Append(yp_sol, PyArray_NewCopy(yp_array, NPY_ANYORDER));

    idid = 0;
    while (idid < 2) {
        // call dassl solver
        DDASSL(dassl_f, &neqn, &t, y, yp,
            &t1, info, &rtol, &atol, &idid, 
            rwork, &lrwork, iwork, &liwork, 
            rpar, ipar);

        // an error occured
        if (idid < -1) {
            success = 0;
            break;
        }

        // store new state in solution lists
        PyList_Append(order_sol, PyLong_FromLong(iwork[7]));
        PyList_Append(t_sol, PyFloat_FromDouble(t));
        PyList_Append(y_sol, PyArray_NewCopy(y_array, NPY_ANYORDER));
        PyList_Append(yp_sol, PyArray_NewCopy(yp_array, NPY_ANYORDER));
    }

    // cleanup
    free(rwork);
    free(iwork);
    Py_XDECREF(f_obj);
    Py_XDECREF(J_obj);
    Py_XDECREF(t_span_obj);
    Py_XDECREF(y_obj);
    Py_XDECREF(yp_obj);
    Py_XDECREF(y_array);
    Py_XDECREF(yp_array);
    
    return Py_BuildValue(
        "{s:N,s:N,s:N,s:N,s:N,s:i,s:i,s:i,s:i,s:i}",
        "success", success ? Py_True : Py_False,
        "order", PyArray_Return(PyArray_FromAny(
                                order_sol,              // Input object
                                NULL,                   // Desired data type (None means let NumPy decide)
                                0,                      // Minimum number of dimensions
                                0,                      // Maximum number of dimensions
                                NPY_ARRAY_DEFAULT,      // Flags
                                NULL)                   // Array description (NULL means default)
                            ),
        "t", PyArray_Return(PyArray_FromAny(
                                t_sol,                  // Input object
                                NULL,                   // Desired data type (None means let NumPy decide)
                                0,                      // Minimum number of dimensions
                                0,                      // Maximum number of dimensions
                                NPY_ARRAY_DEFAULT,      // Flags
                                NULL)                   // Array description (NULL means default)
                            ),
        "y", PyArray_Return(PyArray_FromAny(
                                y_sol,                  // Input object
                                NULL,                   // Desired data type (None means let NumPy decide)
                                0,                      // Minimum number of dimensions
                                0,                      // Maximum number of dimensions
                                NPY_ARRAY_DEFAULT,      // Flags
                                NULL)                   // Array description (NULL means default)
                            ),
        "yp", PyArray_Return(PyArray_FromAny(
                                yp_sol,                 // Input object
                                NULL,                   // Desired data type (None means let NumPy decide)
                                0,                      // Minimum number of dimensions
                                0,                      // Maximum number of dimensions
                                NPY_ARRAY_DEFAULT,      // Flags
                                NULL)                   // Array description (NULL means default)
                            ),
        "nsteps", iwork[10], // IWORK(11) total number of steps
        "nf", iwork[11], // IWORK(12) number of function evaluations
        "njac", iwork[12], // IWORK(13) number of jacobian evaluations
        "nrejerror", iwork[13], // IWORK(14) total number of error test failures
        "nrejnewton", iwork[14] // IWORK(15) total number of convergence test failures
    );

    fail:
        free(rwork);
        free(iwork);
        Py_XDECREF(f_obj);
        Py_XDECREF(J_obj);
        Py_XDECREF(t_span_obj);
        Py_XDECREF(y_obj);
        Py_XDECREF(yp_obj);
        Py_XDECREF(y_array);
        Py_XDECREF(yp_array);
        return NULL;
}

PyDoc_STRVAR(dassl_doc,
"integrate(f, t_span, y0, yp0)\n"
"\n"
"Solve an ODE system using a user-defined derivative function.\n"
"\n"
"Parameters\n"
"----------\n"
"f : callable\n"
"    A Python function that computes the derivatives of the system.\n"
"    The function must have the signature `f(t, y, yp)`, where `t` is the\n"
"    current time, `y` is the state vector, and `yp` is the derivative of the state vector.\n"
"\n"
"t_span : array-like\n"
"    A 2-element list or array defining the time interval `[t_start, t_end]`\n"
"    over which to integrate the system.\n"
"\n"
"y0 : array-like\n"
"    The initial conditions for the state vector `y` at the start of the integration.\n"
"\n"
"yp0 : array-like\n"
"    The initial conditions for the derivative of the state vector `yp` at the start of the integration.\n"
"\n"
"Returns\n"
"-------\n"
"result : dict\n"
"    A dictionary containing the results of the integration. The dictionary has the following keys:\n"
"    - 't_sol': A list of time points at which the solution was recorded.\n"
"    - 'y_sol': A list of state vectors corresponding to each time point.\n"
"    - 'yp_sol': A list of derivative vectors corresponding to each time point.\n"
"\n"
"Raises\n"
"------\n"
"RuntimeError\n"
"    If the integration fails due to an invalid function call or memory error.\n"
"\n"
"Examples\n"
"--------\n"
">>> def rhs(t, y, yp):\n"
">>>     # Example: A simple harmonic oscillator\n"
">>>     yp[0] = y[1]\n"
">>>     yp[1] = -y[0]\n"
">>>     return 0\n"
">>> result = integrate(rhs, [0, 10], [1.0, 0.0], [0.0, -1.0])\n"
">>> print(result['t_sol'])\n"
">>> print(result['y_sol'])\n"
);
