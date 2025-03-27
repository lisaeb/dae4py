import vtk
import os
import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from scipy_dae.integrate import solve_dae
from scipy.optimize._numdiff import approx_derivative
from scipy.sparse import csc_matrix


"""
Numerical simulation of the turbulent flow over a backward-facing step,
see Jovic1994 and Le1997. The velocity flow profiles are found 
on cfd.mace.manchester. The value at x/h = -3 is used for the inlet.
The simple grid proposed by Harlow1965 is used for the spatial discretization.

References:
-----------
Harlow1965: ??? \\
Jovic1994: https://ntrs.nasa.gov/citations/19940028784 \\
Le1997: https://doi.org/10.1017/S0022112096003941 \\
cfd.mace.manchester: http://cfd.mace.manchester.ac.uk/ercoftac/doku.php?id=cases:case031
"""


def create_grid(Lx, Ly, nx, ny, debug=False):
    """Generates grid and step sizes."""

    # number of nodes
    Nx = nx + 1
    Ny = ny + 1

    # grid size (equispaced)
    dx = Lx / nx
    dy = Ly / ny

    # coordinate of each grid (cell center)
    xij = (np.arange(nx) + 0.5) * dx
    yij = (np.arange(ny) + 0.5) * dy

    # coordinate of each grid (cell corner)
    xi2j2 = (np.arange(Nx)) * dx
    yi2j2 = (np.arange(Ny)) * dy

    # visualize mesh for debugging purpose
    if debug:
        Xij, Yij = np.meshgrid(xij, yij)
        Xi2j2, Yi2j2 = np.meshgrid(xi2j2, yi2j2)
        _, ax = plt.subplots()
        ax.plot(Xij, Yij, "ok", label="cell centers")
        ax.plot(Xi2j2, Yi2j2, "xk", label="cell corners")
        ax.legend()
        ax.grid()
        ax.set_aspect("equal")
        plt.show()

    return xij, yij, xi2j2, yi2j2, dx, dy


def initial_conditions(nx, ny):
    """Set initial conditions."""

    u_init = np.zeros((nx + 1, ny + 2))
    v_init = np.zeros((nx + 2, ny + 1))
    p_init = np.zeros((nx, ny))

    ut_init = np.zeros((nx + 1, ny + 2))
    vt_init = np.zeros((nx + 2, ny + 1))
    pt_init = np.zeros((nx, ny))

    y0 = np.concatenate(
        (
            u_init[1:nx, 1 : ny + 1].flatten(),
            v_init[1 : nx + 1, 1:ny].flatten(),
            p_init.flatten(),
        )
    )
    yp0 = np.concatenate(
        (
            ut_init[1:nx, 1 : ny + 1].flatten(),
            vt_init[1 : nx + 1, 1:ny].flatten(),
            pt_init.flatten(),
        )
    )

    return y0, yp0


def jac_sparsity(F, t0, y0, yp0, eps=1e-2, debug=False):
    """Estimate Jacobian structure using perturbed initial conditions and
    finite differences."""

    if debug:
        eps = 0

    Jy0 = approx_derivative(
        lambda y: F(t0, y, yp0),
        y0 + np.random.rand(len(y0)) * eps,
        method="2-point",
    )
    sparsity_Jy = csc_matrix(Jy0)
    print(f"Jy0.shape: {Jy0.shape}")
    # print(f"np.linalg.matrix_rank(J0): {np.linalg.matrix_rank(Jy0)}")

    Jyp0 = approx_derivative(
        lambda yp: F(t0, y0, yp),
        yp0 + np.random.rand(len(yp0)) * eps,
        method="2-point",
    )
    sparsity_Jyp = csc_matrix(Jyp0)
    print(f"Jyp0.shape: {Jyp0.shape}")
    # print(f"np.linalg.matrix_rank(Jyp0): {np.linalg.matrix_rank(Jyp0)}")

    if debug:
        nu = (nx - 1) * ny
        nv = nx * (ny - 1)
        np_ = nx * ny
        n = nu + nv + np_
        C = Jy0[: nu + nv, nu + nv :]
        CT = Jy0[nu + nv :, : nu + nv]
        C *= -2
        print(f"C:\n{C}")
        print(f"CT.T:\n{CT.T}")
        error = np.linalg.norm(C - CT.T)
        print(f"error(C - CT.T): {error}")
        fig, ax = plt.subplots(1, 2)
        ax[0].title.set_text("Jy0")
        ax[0].spy(Jy0)
        ax[1].title.set_text("Jyp0")
        ax[1].spy(Jyp0)
        plt.show()
        exit()

    return (sparsity_Jy, sparsity_Jyp)


def apply_boundary_conditions(u_red, v_red, p_red, BC):
    """Applies Dirichlet boundary conditions to velocity fields."""

    # unpack dictionary
    u_left = BC["u_left"]
    u_right = BC["u_right"]
    u_bot = BC["u_bot"]
    u_top = BC["u_top"]

    v_left = BC["v_left"]
    v_right = BC["v_right"]
    v_bot = BC["v_bot"]
    v_top = BC["v_top"]

    inner_u = BC["inner_u"]
    inner_v = BC["inner_v"]
    inner_p = BC["inner_p"]

    # Dirichlet boundary conditions for velocities
    # - u
    if u_left is None:
        u_red[0, :] = u_red[1, :]
    else:
        u_red[0, :] = 2 * u_left - u_red[1, :]

    if u_right is None:
        u_red[-1, :] = u_red[-2, :]
    else:
        u_red[-1, :] = 2 * u_right - u_red[-2, :]

    if u_bot is None:
        u_red[:, 0] = u_red[:, 1]
    else:
        u_red[:, 0] = 2 * u_bot - u_red[:, 1]

    if u_top is None:
        u_red[:, -1] = u_red[:, -2]
    else:
        u_red[:, -1] = 2 * u_top - u_red[:, -2]

    # - v
    if v_left is None:
        v_red[0, :] = v_red[1, :]
    else:
        v_red[0, :] = 2 * v_left - v_red[1, :]

    if v_right is None:
        v_red[-1, :] = v_red[-2, :]
    else:
        v_red[-1, :] = 2 * v_right - v_red[-2, :]

    if v_top is None:
        # v_red[:, -1] = v_red[:, -2]
        v_red[1:-1, -1] = v_red[1:-1, -2]
    else:
        v_red[:, -1] = 2 * v_top - v_red[:, -2]

    if v_bot is None:
        # v_red[:, 0] = v_red[:, 1]
        v_red[1:-1, 0] = v_red[1:-1, 1]
    else:
        v_red[:, 0] = 2 * v_bot - v_red[:, 1]


def redundant_coordinates(t, y, yp, nx, ny, BC):
    """Converts state and derivatives into structured 2D arrays with boundary
    conditions applied."""
    # unpack state vector and derivatives
    nu = (nx - 1) * ny
    nv = nx * (ny - 1)
    split = np.cumsum([nu, nv])
    u, v, p = np.array_split(y, split)
    ut, vt, pt = np.array_split(yp, split)

    # reshape 2D
    u = u.reshape((nx - 1, ny))
    v = v.reshape((nx, ny - 1))
    p = p.reshape((nx, ny))
    ut = ut.reshape((nx - 1, ny))
    vt = vt.reshape((nx, ny - 1))
    pt = pt.reshape((nx, ny))

    # build redundant coordinates
    u_red = np.zeros((nx + 1, ny + 2))
    v_red = np.zeros((nx + 2, ny + 1))
    p_red = np.zeros((nx, ny))
    ut_red = np.zeros((nx + 1, ny + 2))
    vt_red = np.zeros((nx + 2, ny + 1))
    pt_red = np.zeros((nx, ny))

    # interior velocites are the unknowns; all pressures are unknown
    u_red[1:-1, 1:-1] = u
    v_red[1:-1, 1:-1] = v
    p_red = p

    ut_red[1:-1, 1:-1] = ut
    vt_red[1:-1, 1:-1] = vt
    pt_red = pt

    # boundary conditions
    apply_boundary_conditions(u_red, v_red, p_red, BC(t))

    return u_red, v_red, p_red, ut_red, vt_red, pt_red


def F(t, y, yp, eps=1e-12):
    # current time
    print(f"t: {t}")

    # set boundary conditions
    u, v, p, ut, vt, pt = redundant_coordinates(t, y, yp, nx, ny, BC)
    p = pt  # note: Index reduction!

    # interpolate velocities
    uij = 0.5 * (u[:-1, 1:-1] + u[1:, 1:-1])
    u2ij = uij**2
    vij = 0.5 * (v[1:-1, :-1] + v[1:-1, 1:])
    v2ij = vij**2
    ui2j2 = 0.5 * (u[:, :-1] + u[:, 1:])
    vi2j2 = 0.5 * (v[:-1] + v[1:])

    # momentum equation for u
    Fu = (
        ut[1:-1, 1:-1]
        + (u2ij[1:] - u2ij[:-1]) / dx
        + (ui2j2[1:-1, 1:] * vi2j2[1:-1, 1:] - ui2j2[1:-1, :-1] * vi2j2[1:-1, :-1]) / dy
        + (p[1:] - p[:-1]) / dx
        # - 2 * (p[1:] - p[:-1]) / dx
        - nu
        * (
            (u[2:, 1:-1] - 2 * u[1:-1, 1:-1] + u[:-2, 1:-1]) / dx**2
            + (u[1:-1, 2:] - 2 * u[1:-1, 1:-1] + u[1:-1, :-2]) / dy**2
        )
    )

    # momentum equation for v
    Fv = (
        vt[1:-1, 1:-1]
        + (ui2j2[1:, 1:-1] * vi2j2[1:, 1:-1] - ui2j2[:-1, 1:-1] * vi2j2[:-1, 1:-1]) / dx
        + (v2ij[:, 1:] - v2ij[:, :-1]) / dy
        + (p[:, 1:] - p[:, :-1]) / dy
        # - 2 * (p[:, 1:] - p[:, :-1]) / dy
        - nu
        * (
            (v[2:, 1:-1] - 2 * v[1:-1, 1:-1] + v[:-2, 1:-1]) / dx**2
            + (v[1:-1, 2:] - 2 * v[1:-1, 1:-1] + v[1:-1, :-2]) / dy**2
        )
    )

    # continuity equation
    Fp = (
        (u[1:, 1:-1] - u[:-1, 1:-1]) / dx
        + (v[1:-1, 1:] - v[1:-1, :-1]) / dy
        # + eps * p # regularization term
    )

    # zero mean pressure
    # Fp[-1, -1] = np.sum(p, axis=(0, 1)) / (Lx * Ly)

    # # fix one pressure value
    # Fp[-1, -1] = p[-1, -1]

    return np.concatenate(
        (
            Fu.flatten(),
            Fv.flatten(),
            Fp.flatten(),
        )
    )


def animate(x, y, u, v, p, interval=1):
    fig, ax = plt.subplots()

    def update(num):
        ax.clear()
        ax.set_xlim(-0.25 * Lx, 1.25 * Lx)
        ax.set_ylim(-0.25 * Ly, 1.25 * Ly)
        ax.set_aspect("equal")
        # ax.plot(x, y, "ok")

        # # with np.errstate(divide='ignore'):
        # quiver = ax.quiver(x, y, u[:, :, num], v[:, :, num])

        contourf = ax.contourf(
            x, y, np.sqrt(u[:, :, num] ** 2 + v[:, :, num] ** 2), alpha=0.5
        )
        streamplot = ax.streamplot(x, y, u[:, :, num], v[:, :, num], density=1.5)
        return contourf, streamplot

    anim = animation.FuncAnimation(
        fig, update, frames=u.shape[-1], interval=interval, blit=False, repeat=True
    )
    plt.show()


def smoothstep2(x, x_min=0, x_max=1):
    x = np.clip((x - x_min) / (x_max - x_min), 0, 1)
    return 6 * x**5 - 15 * x**4 + 10 * x**3


if __name__ == "__main__":
    ############
    # parameters
    ############
    # domain
    h = 0.96
    H = 5 * h
    Lx = 20 * h
    Ly = 2 * (h + H)

    # number of cell centers per h
    # nxh, nyh = 1, 1
    nxh, nyh = 2, 2
    # nxh, nyh = 3, 3 # good fit with reattachment length (without startup)
    # nxh, nyh = 4, 4
    # nxh, nyh = 5, 5
    # nxh, nyh = 6, 6

    nx = int(Lx / h * nxh)
    ny = int(Ly / h * nyh)

    # # Le1997
    # nx = 768
    # ny = 192

    print(f"nx: {nx}")
    print(f"ny: {ny}")

    # reference velocity
    U0 = 7.72

    # dynamic viscosity
    mu = 1.5e-5

    # density
    rho = 1.2

    # kinematic viscosity
    nu = mu / rho

    # linear spaced vertical mesh points
    y = np.linspace(0, Ly, ny + 2)

    # laminar velocity profile
    # u_left_profile = U0 * 4 * y * (Ly - y) / Ly**2
    # u_left_profile = U0 * np.maximum(0, 4 * (y - h) * (Ly - h - (y - h)) / (Ly - h)**2)
    u_left_profile = U0 * np.maximum(
        0, 4 * (y - h) * (Ly - 2 * h - (y - h)) / (Ly - 2 * h) ** 2
    )

    # # turbulent velocity profile
    # p = 7
    # # p = 10
    # p = 20
    # # p = 50
    # # p = 100
    # R = Ly / 2
    # u_left_profile = U0 * np.where(
    #     y <= R,
    #     # (y / R) ** (1 / p),
    #     # ((2 * R - y) / R)** (1 / p),
    #     np.where(
    #         y <= h,
    #         0,
    #         ((y - h) / R) ** (1 / p),
    #     ),
    #     np.where(
    #         y >= 2 * R - h,
    #         0,
    #         ((2 * R - y - h) / R) ** (1 / p),
    #     ),
    # )

    print(f"u_left: {u_left_profile}")
    fig, ax = plt.subplots()
    ax.plot(u_left_profile, y)
    plt.show()
    exit()

    # reference at x/h = -3
    ref = np.loadtxt(f"examples/DAE/backward_facing_step/reference/x-181.dat")
    y_ref = ref[:, 0]
    y_ref += 6 * h - y_ref[-1]
    u_ref = ref[:, 1] * U0
    v_ref = ref[:, 2] * U0

    y_ref = np.concatenate((y_ref, Ly - np.flip(y_ref)))
    u_ref = np.concatenate((u_ref, np.flip(u_ref)))
    v_ref = np.concatenate((v_ref, -np.flip(v_ref)))
    print(f"Ly: {Ly}")

    y_u = np.linspace(0, Ly, ny + 2)
    idx = np.where(np.logical_and(h <= y_u, y_u <= h + 2 * H))
    u_left_profile = np.zeros_like(y_u)
    u_left_profile[idx] = np.interp(y_u[idx], y_ref, u_ref)

    y_v = np.linspace(0, Ly, ny + 1)
    idx = np.where(np.logical_and(h <= y_v, y_v <= h + 2 * H))
    v_left_profile = np.zeros_like(y_v)
    v_left_profile[idx] = np.interp(y_v[idx], y_ref, v_ref)

    # fig, ax = plt.subplots(2, 1)

    # ax[0].title.set_text(f"inlet profile")
    # ax[0].plot(u_ref, y_ref, "-", label="u_ref")
    # ax[0].plot(u_left_profile, y_u, "--o", label="u_ref interp")
    # ax[0].set_xlabel("u / U0")
    # ax[0].set_ylabel("y / h")
    # ax[0].grid()
    # ax[0].legend()

    # ax[1].plot(v_ref, y_ref, label="v_ref")
    # ax[1].plot(v_left_profile, y_v, "--o", label="v_ref interp")
    # ax[1].set_xlabel("v / U0")
    # ax[1].set_ylabel("y / h")
    # ax[1].grid()
    # ax[1].legend()

    # plt.show()
    # exit()

    # boundary conditions
    def BC(t):
        # startup = 0.25
        startup = 0.2
        return {
            "u_top": 0,
            "u_bot": 0,
            "u_left": u_left_profile * smoothstep2(t, t0, startup * (t1 - t0)),
            "u_right": None,
            "v_top": 0,
            "v_bot": 0,
            "v_left": v_left_profile * smoothstep2(t, t0, startup * (t1 - t0)),
            "v_right": None,
            "inner_u": np.s_[1:nx, 1 : ny + 1],
            "inner_v": np.s_[1 : nx + 1, 1:ny],
            "inner_p": np.s_[:nx, :ny],
        }

    # note: only required to show C.T = C
    # BC = {
    #     "u_top": 0,
    #     "u_bot": 0,
    #     "u_left": 0,
    #     "u_right": 0,
    #     "v_top": 0,
    #     "v_bot": 0,
    #     "v_left": 0,
    #     "v_right": 0,
    #     "inner_u": np.s_[1:nx, 1:ny + 1],
    #     "inner_v": np.s_[1:nx + 1, 1:ny],
    #     "inner_p": np.s_[:nx, :ny],
    # }

    # generate the grid
    xij, yij, xi2j2, yi2j2, dx, dy = create_grid(Lx, Ly, nx, ny)

    # initial conditions
    y0, yp0 = initial_conditions(nx, ny)

    print(f"DOF's: {len(y0)}")
    exit()

    # time span
    t0 = 0
    # t1 = 2
    # t1 = 10
    # t1 = 20
    # t1 = 50
    t1 = 100
    # t1 = 200
    # t1 = 500
    # t1 = 1e3
    t_span = (t0, t1)
    t_eval = np.linspace(t0, t1, num=int(1e2))
    # t_eval = np.linspace(t0, t1, num=int(1e3))

    # compute Jacobian structure
    jac_sparsity = jac_sparsity(F, t0, y0, yp0)

    # method = "BDF"
    method = "Radau"

    # solver options
    atol = rtol = 1e-3

    # solve the system
    start = time.time()
    sol = solve_dae(
        F,
        t_span,
        y0,
        yp0,
        atol=atol,
        rtol=rtol,
        method=method,
        t_eval=t_eval,
        jac_sparsity=jac_sparsity,
        first_step=1e-3,
        # max_step=1e-1,
        stages=1,
        # max_step=5e-1,
        # max_step=1,
        # jac_recompute_rate=1e-1,
    )
    end = time.time()
    print(f"elapsed time: {end - start}")
    t = sol.t
    sol_y = sol.y
    sol_yp = sol.yp
    success = sol.success
    status = sol.status
    message = sol.message
    print(f"success: {success}")
    print(f"status: {status}")
    print(f"message: {message}")
    print(f"nfev: {sol.nfev}")
    print(f"njev: {sol.njev}")
    print(f"nlu: {sol.nlu}")

    # reconstruct solution
    Xij, Yij = np.meshgrid(xij, yij, indexing="ij")
    Xi2j2, Yi2j2 = np.meshgrid(xi2j2, yi2j2, indexing="ij")

    nt = len(t)
    u = np.zeros((nx + 1, ny + 2, nt))
    v = np.zeros((nx + 2, ny + 1, nt))
    p = np.zeros((nx, ny, nt))
    ut = np.zeros((nx + 1, ny + 2, nt))
    vt = np.zeros((nx + 2, ny + 1, nt))
    pt = np.zeros((nx, ny, nt))
    for i in range(nt):
        u[:, :, i], v[:, :, i], p[:, :, i], ut[:, :, i], vt[:, :, i], pt[:, :, i] = (
            redundant_coordinates(t[i], sol_y[:, i], sol_yp[:, i], nx, ny, BC)
        )

        # # get zero mean pressure
        # pt[:, :, i] -= np.sum(pt[:, :, i], axis=(0, 1))

    # interpolate velocity at cell centers and cell corners
    uij = 0.5 * (u[:-1, 1:-1] + u[1:, 1:-1])
    ui2j2 = 0.5 * (u[:, :-1] + u[:, 1:])
    vij = 0.5 * (v[1:-1, :-1] + v[1:-1, 1:])
    vi2j2 = 0.5 * (v[:-1, :] + v[1:, :])

    # # transpose data for "xy" meshgrid and streamplot
    # # ui2j2 = ui2j2.transpose(1, 0, 2)
    # # vi2j2 = vi2j2.transpose(1, 0, 2)
    # uij = uij.transpose(1, 0, 2)
    # vij = vij.transpose(1, 0, 2)
    # p = p.transpose(1, 0, 2)

    # Xij, Yij = np.meshgrid(xij, yij, indexing="xy")
    # # animate(Xij, Yij, uij, vij, p)

    ###############################
    # visualize reattachment length
    # xr = 6.28h due to Le & Moin
    ###############################
    fig, ax = plt.subplots()
    ax.title.set_text(f"reattachment length")
    # ax.plot(Xij[:, 0] / h, uij[:, 0, -1], label="u_{i0}")
    # ax.plot(Xij[:, 0] / h, 0 * uij[:, 0, -1])
    # ax.plot([6.28, 6.28], [np.min(uij[:, 0, -1]), np.max(uij[:, 0, -1])], label="Le & Moin 1997")
    ax.plot(Xi2j2[:, 1] / h, ui2j2[:, 1, -1], label="u_{i+1/2,1/2}")
    ax.plot(Xi2j2[:, 1] / h, 0 * ui2j2[:, 1, -1])
    ax.plot(
        [6.28, 6.28],
        [np.min(ui2j2[:, 1, -1]), np.max(ui2j2[:, 1, -1])],
        label="Le & Moin 1997",
    )
    ax.grid()
    ax.legend()
    ax.set_xlabel("x / h")
    plt.show()
    # exit()

    #################################
    # compare with reference solution
    #################################
    fig, ax = plt.subplots(2, 5)

    number_xh = [
        (360, 4),
        (411, 6),
        (513, 10),
        (641, 15),
        (744, 19),
    ]
    for i, (number, xh) in enumerate(number_xh):
        ref = np.loadtxt(f"examples/DAE/backward_facing_step/reference/x-{number}.dat")
        y_ref = ref[:, 0]
        u_ref = ref[:, 1]
        v_ref = ref[:, 2]

        idx = (np.abs(xi2j2 - xh * h)).argmin()

        ax[0, i].title.set_text(f"x / h: {xh}")
        ax[0, i].plot(u_ref, y_ref, label="u_ref")
        ax[0, i].plot(ui2j2[idx, :, -1] / U0, yi2j2 / h, label="u")
        ax[0, i].set_xlabel("u / U0")
        ax[0, i].set_ylabel("y / h")
        ax[0, i].grid()
        ax[0, i].legend()

        ax[1, i].title.set_text(f"x / h: {xh}")
        ax[1, i].plot(v_ref, y_ref, label="v_ref")
        ax[1, i].plot(vi2j2[idx, :, -1] / U0, yi2j2 / h, label="v")
        ax[1, i].set_xlabel("v / U0")
        ax[1, i].set_ylabel("y / h")
        ax[1, i].grid()
        ax[1, i].legend()

    plt.show()
    # exit()

    ############
    # vtk export
    ############
    # define output directory
    output_dir = "backward_facing_step"
    os.makedirs(output_dir, exist_ok=True)

    # create .pvd file
    pvd_filename = os.path.join(output_dir, "backward_facing_step.pvd")
    pvd_file = open(pvd_filename, "w")
    pvd_file.write('<?xml version="1.0"?>\n')
    pvd_file.write('  <VTKFile type="Collection">\n')
    pvd_file.write("    <Collection>\n")

    # vtu writer
    writer = vtk.vtkXMLUnstructuredGridWriter()
    writer.SetDataModeToAscii()  # debug

    for k in range(nt):
        filename = f"data_{k:03d}.vtu"
        full_path = os.path.join(output_dir, filename)

        # create grid
        grid = vtk.vtkUnstructuredGrid()

        # add points
        vtkpoints = vtk.vtkPoints()
        vtkpoints.Allocate(Xi2j2.size)
        for i in range(nx):
            for j in range(ny):
                vtkpoints.InsertNextPoint((Xi2j2[i, j], Yi2j2[i, j], 0))
                vtkpoints.InsertNextPoint((Xi2j2[i + 1, j], Yi2j2[i + 1, j], 0))
                vtkpoints.InsertNextPoint((Xi2j2[i + 1, j + 1], Yi2j2[i + 1, j + 1], 0))
                vtkpoints.InsertNextPoint((Xi2j2[i, j + 1], Yi2j2[i, j + 1], 0))

        grid.SetPoints(vtkpoints)

        # define cells
        grid.Allocate(nx * ny)
        cell_type = vtk.VTK_QUAD  # 90
        offset = 0
        connectivity = np.arange(4)
        for i in range(nx):
            for j in range(ny):
                grid.InsertNextCell(cell_type, len(connectivity), connectivity + offset)
                offset += 4

        # add velocity as point data
        u_val = ui2j2[:, :, k]
        v_val = vi2j2[:, :, k]
        pdata = grid.GetPointData()
        u_array = vtk.vtkDoubleArray()
        u_array.SetName("u")
        u_array.SetNumberOfComponents(3)
        for i in range(nx):
            for j in range(ny):
                u_array.InsertNextTuple3(u_val[i, j], v_val[i, j], 0)
                u_array.InsertNextTuple3(u_val[i + 1, j], v_val[i + 1, j], 0)
                u_array.InsertNextTuple3(u_val[i + 1, j + 1], v_val[i + 1, j + 1], 0)
                u_array.InsertNextTuple3(u_val[i, j + 1], v_val[i, j + 1], 0)
        pdata.AddArray(u_array)

        # add pressure as cell data
        p_val = pt[:, :, k]
        cdata = grid.GetCellData()
        carray = vtk.vtkDoubleArray()
        carray.SetName("p")
        carray.SetNumberOfComponents(1)
        for i in range(nx):
            for j in range(ny):
                carray.InsertNextTuple1(p_val[i, j])
        cdata.AddArray(carray)

        # write the VTU file
        writer.SetFileName(full_path)
        writer.SetInputData(grid)
        writer.Write()

        # add to PVD file
        pvd_file.write(f'     <DataSet timestep="{t[k]}" file="{filename}"/>\n')

    # finalize pvd file
    pvd_file.write("    </Collection>\n")
    pvd_file.write("  </VTKFile>\n")
    pvd_file.close()
