# Precompilation workload executed during `docker build` so that
# DifferentialEquations.jl, Plots.jl (GR SVG backend), CSV.jl, and DataFrames.jl
# compile cleanly ahead of time and launch in seconds for every tutorial student.

ENV["GKSwstype"] = "100"

using DifferentialEquations
using Plots
using CSV
using DataFrames

gr()

function _precompile_toy(dy, y, p, t)
    A = maximum([y[1], 0.0])
    B = maximum([y[2], 0.0])
    C = maximum([y[3], 0.0])
    dy[1] = 1.0 - A * 2.0
    dy[2] = A * 2.0 - B * 3.0
    dy[3] = B * 3.0 - C * 4.0
end

y0 = [1.0, 0.0, 0.0]
f = ODEFunction(_precompile_toy)
prob = ODEProblem(f, y0, (0.0, 10.0))
sol1 = solve(prob, abstol=1e-5, reltol=1e-3, saveat=1.0)
sol2 = solve(prob, abstol=1e-5, reltol=1e-3)

plt = plot(
    sol2,
    label = ["A" "B" "C"],
    xlabel = "Time (min)",
    ylabel = "Concentration (nM)",
    title = "Precompile check",
    lw = 2.5,
)
# Render SVG to an in-memory buffer to exercise the GR SVG codepath
io = IOBuffer()
show(io, MIME("image/svg+xml"), plt)

# Exercise CSV + DataFrames reading
df = CSV.read(IOBuffer("Parameter,Value\nk1_Aexp,1\n"), DataFrame)
show(devnull, df)
println("Precompile workload completed successfully!")
